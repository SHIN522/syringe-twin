"""Twin <-> OpenPLC link over Modbus TCP (PLC mode, DECISIONS D9-D10).

Every exchange writes the twin's signals to %MW0..%MW27 and reads the PLC's
coils %QX0.0..%QX1.3 and registers %QW0..%QW6. Addresses and meanings:
docs/plc/tag_dictionary.csv. Behaviour: docs/plc/PLC_SPEC.md section 5.
"""
from time import monotonic
from .commands import validate, audit, apply, check_injectable, resume_s2
from .control import room, prediction
from .events import alarm, clear_alarm, active_alarms, trip_s2

MW = 1024
PULSE_S = 0.2       # command pulses are held for >= 10 PLC scans
STALE_S = 1.0       # PLC heartbeat watchdog (twin side of F002)
RETRY_S = 1.0
MAX_SPEED = 10
STATE_CODES = {'STOPPED': 0, 'STARVED': 1, 'RUNNING': 2, 'BLOCKED': 3, 'FAULT': 4, 'MAINT': 5}
COILS = ('M_SYS_RUN', 'Q_LAMP_GREEN', 'Q_LAMP_AMBER', 'Q_LAMP_RED', 'Q_HORN', 'F201', 'F001',
         'F002', 'M_ANY_FAULT', 'F201_INJECTED', 'S2_RELEASE_PERMIT', 'M_S2_REPAIRED')
REGISTERS = ('S2_VERDICT_SEQ', 'PLC_HEARTBEAT', 'C_IN', 'C_GOOD', 'C_REJECT', 'BOX_FILL', 'BOXES_TOTAL')
PULSES = {'CMD_START': 0, 'CMD_STOP': 1, 'CMD_RESET': 2, 'CMD_INJECT_F201': 15}


def word(value):
    return int(value) & 0xFFFF


class PlcBridge:
    def __init__(self, host='127.0.0.1', port=502, client=None, clock=monotonic):
        if client is None:
            from pymodbus.client import ModbusTcpClient
            client = ModbusTcpClient(host, port=port, timeout=0.5)
        self.client, self.clock = client, clock
        self.host, self.port = host, port
        self.pulses = {}
        self.coils = dict.fromkeys(COILS, False)
        self.registers = dict.fromkeys(REGISTERS, 0)
        self.heartbeat = 0
        self.link_ok = False
        self.link_fault = False
        self.error = None
        self.next_retry = 0.0
        self.plc_hb, self.plc_hb_at = None, None
        self.latency_ms = None
        self.exchanges = 0
        self.base = None

    # ---- setup -----------------------------------------------------------
    def attach(self, s):
        s.config['control']['f201_source'] = 'plc'
        s.plc['verdict_seq'] = None
        s.speed = min(s.speed, MAX_SPEED)

    def close(self):
        self.client.close()

    # ---- one exchange (called every ~20 ms wall from the service loop) ----
    def outputs(self, s):
        now = self.clock()
        st2 = s.stations['S2']
        steps = s.config['stations']['S2']['steps']
        cycles = prediction(s)
        values = [0] * 28
        for name, index in PULSES.items():
            values[index] = int(self.pulses.get(name, 0) > now)
        values[3] = int(not s.estop_active)
        values[4] = int(st2.tool_ok)
        values[5] = word(round((st2.force or 0) * 10))
        values[6] = st2.press_samples % 32768
        values[7] = s.counts['good'] % 32768
        values[8] = s.counts['reject'] % 32768
        values[9] = self.heartbeat
        values[10] = int(any(a['sev'] == 'WARN' for a in active_alarms(s)))
        values[11] = int(any(st.state == 'BLOCKED' for st in s.stations.values()))
        values[12] = int(st2.pallet is not None and st2.step_i >= len(steps))
        values[13] = int(room(s, 'B3'))
        values[14] = s.counts['in'] % 32768
        for n, name in enumerate(('IN', 'S1', 'S2', 'S3', 'S4', 'OUT')):
            values[20 + n] = STATE_CODES[s.stations[name].state]
        values[26] = round(st2.wear * 1000)
        values[27] = word(-1 if cycles is None else min(32767, round(cycles)))
        return values

    def exchange(self, s):
        now = self.clock()
        if not self.link_ok and now < self.next_retry:
            return
        self.heartbeat = (self.heartbeat + 1) % 32768
        try:
            if not self.client.connected and not self.client.connect():
                raise ConnectionError(f'no Modbus server at {self.host}:{self.port}')
            began = self.clock()
            reply = self.client.write_registers(MW, self.outputs(s))
            coils = self.client.read_coils(0, count=len(COILS))
            regs = self.client.read_holding_registers(0, count=len(REGISTERS))
            for response in (reply, coils, regs):
                if response.isError():
                    raise ConnectionError(f'Modbus exception: {response}')
            self.latency_ms = (self.clock() - began) * 1000
        except Exception as exc:  # any transport failure is a lost link
            self._lost(s, str(exc) or type(exc).__name__)
            return
        values = dict(zip(REGISTERS, regs.registers))
        if values['PLC_HEARTBEAT'] != self.plc_hb:
            self.plc_hb, self.plc_hb_at = values['PLC_HEARTBEAT'], now
        elif now - self.plc_hb_at > STALE_S:
            self._lost(s, 'PLC heartbeat stopped (program not running?)')
            return
        self.link_ok, self.error = True, None
        self.exchanges += 1
        self._apply(s, dict(zip(COILS, coils.bits[:len(COILS)])), values)

    def _lost(self, s, reason):
        self.link_ok, self.error = False, reason
        self.next_retry = self.clock() + RETRY_S
        self.plc_hb = None
        self.client.close()
        if not self.link_fault:
            self.link_fault = True
            alarm(s, 'F002', None, 'PLC link lost: ' + reason)
        s.run = False

    def _apply(self, s, coils, values):
        before = self.coils
        self.coils, self.registers = coils, values
        # F001 E-stop latch (P1-R2)
        s.estop_latched = coils['F001']
        if coils['F001'] and not before['F001']:
            alarm(s, 'F001', None, 'Emergency stop latched in PLC.')
        if before['F001'] and not coils['F001']:
            clear_alarm(s, 'F001')
        # F201 overload (P5-R1/R2) and its reset (P8-R2)
        st2 = s.stations['S2']
        if coils['F201'] and not st2.fault:
            trip_s2(s, injected=coils['F201_INJECTED'])
        if not coils['F201'] and st2.fault == 'F201' and before['F201']:
            resume_s2(s)
        # Verdict echo = INSERT permissive (P5-R3)
        s.plc['verdict_seq'] = values['S2_VERDICT_SEQ']
        # F002 link watchdog: clear only when both sides are healthy
        if coils['F002'] and not before['F002']:
            alarm(s, 'F002', None, 'PLC watchdog: twin heartbeat lost.')
        if not coils['F002'] and not self.link_fault:
            clear_alarm(s, 'F002')
        # Run permissive (P1-R1)
        s.run = coils['M_SYS_RUN'] and not self.link_fault
        if self.base is None and self.exchanges >= 5:
            self.base = {'twin': dict(s.counts),
                         'plc': {k: values[k] for k in ('C_IN', 'C_GOOD', 'C_REJECT')}}

    # ---- operator commands in PLC mode -----------------------------------
    def pulse(self, name):
        self.pulses[name] = self.clock() + PULSE_S

    def command(self, s, cmd, args, user):
        validate(cmd, user)
        if cmd == 'start':
            if s.estop_active or self.coils['F001']:
                raise ValueError('PLC: E-stop latched. Release E-stop, Reset, then Start.')
            if self.link_fault or not self.link_ok:
                raise ValueError('PLC link is down. Restore the PLC, Reset, then Start.')
            self.pulse('CMD_START')
            result = 'Start sent to PLC.'
        elif cmd == 'stop':
            self.pulse('CMD_STOP')
            result = 'Stop sent to PLC; parts and process progress retained.'
        elif cmd == 'reset':
            self.pulse('CMD_RESET')
            if self.link_ok and self.link_fault:
                self.link_fault = False
            result = 'Reset sent to PLC.'
        elif cmd == 'estop':
            active = args.get('active')
            if type(active) is not bool:
                raise ValueError('estop requires active: true or false.')
            s.estop_active = active
            if active:
                s.run = False  # fail-safe: do not wait for the next scan
            result = ('E-stop engaged: PLC input I_ESTOP_OK = 0.' if active
                      else 'E-stop released; Reset then Start.')
        elif cmd == 'inject_fault':
            if args.get('code') != 'F201':
                raise ValueError('Fault injection is available for F201 only.')
            check_injectable(s)
            self.pulse('CMD_INJECT_F201')
            result = 'F201 injection sent to PLC.'
        elif cmd == 'set_speed' and args.get('x') not in (1, 2, 5, 10):
            raise ValueError('PLC mode supports 1×, 2×, 5× and 10×.')
        else:
            result = apply(s, cmd, args)
        return audit(s, cmd, args, user, result)

    def status(self, s):
        counters = {k: self.registers[k] for k in ('C_IN', 'C_GOOD', 'C_REJECT', 'BOX_FILL', 'BOXES_TOTAL')}
        consistent = None
        if self.base:
            consistent = all(self.registers[p] - self.base['plc'][p] == s.counts[t] - self.base['twin'][t]
                             for p, t in (('C_IN', 'in'), ('C_GOOD', 'good'), ('C_REJECT', 'reject')))
        return {'mode': 'plc', 'endpoint': f'{self.host}:{self.port}', 'link_ok': self.link_ok,
                'link_fault': self.link_fault, 'error': self.error, 'latency_ms': self.latency_ms,
                'coils': dict(self.coils), 'counters': counters, 'counters_consistent': consistent}


def from_env(value):
    """SYRINGETWIN_PLC=host[:port] enables PLC mode."""
    if not value:
        return None
    host, _, port = value.partition(':')
    return PlcBridge(host or '127.0.0.1', int(port or 502))
