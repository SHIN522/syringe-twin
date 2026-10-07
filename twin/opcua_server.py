"""OPC UA server for the twin (DECISIONS D11, D13).

Publishes the latest service payload every 0.5 s wall time under ns=2;s=Line1.*,
using the node IDs in docs/plc/tag_dictionary.csv. Undefined values are sent
with Bad_WaitingForInitialData quality instead of an invented number.
Line1.HMI.* are the only writable nodes: an HMI (FUXA) writes a command bit, the
server runs the same validated, audited command as the dashboard (user "HMI (OPC UA)")
and clears the bit; the outcome is published in Line1.HMI.LastResult.
Bound to localhost, no security: a demonstration interface, not a plant network.
"""
import asyncio
import logging
from threading import Event, Thread
from asyncua import Server, ua

ENDPOINT = 'opc.tcp://127.0.0.1:4840/syringetwin/'
NAMESPACE = 'urn:syringetwin'
STATE_CODES = {'STOPPED': 0, 'STARVED': 1, 'RUNNING': 2, 'BLOCKED': 3, 'FAULT': 4, 'MAINT': 5}
D, I, B, S = ua.VariantType.Double, ua.VariantType.Int32, ua.VariantType.Boolean, ua.VariantType.String
DEFAULTS = {D: 0.0, I: 0, B: False, S: ''}


def flatten(payload):
    """Map one /api/live payload to {node path: (value or None, variant type)}."""
    s, k, m = payload['snapshot'], payload['kpi'], payload['meta']
    active = [a for a in s['alarms']]
    out = {
        'Line1.SimTime': (s['t'], D), 'Line1.Speed': (s['speed'], I), 'Line1.Run': (s['run'], B),
        'Line1.Lamp': (s['lamp'], S), 'Line1.Profile': (m.get('profile') or 'default', S),
        'Line1.Panel.EStopActive': (m['estop_active'], B), 'Line1.Panel.EStopLatched': (m['estop_latched'], B),
        'Line1.Alarms.Active': (','.join(a['code'] for a in active), S),
        'Line1.Alarms.AnyFault': (any(a['sev'] == 'FAULT' for a in active), B),
        'Line1.Alarms.AnyWarn': (any(a['sev'] == 'WARN' for a in active), B),
        'Line1.KPI.Throughput': (k['th_ph'], D), 'Line1.KPI.LineCycleTime': (k['line_ct_s'], D),
        'Line1.KPI.LeadTime': (k['lead_s'], D), 'Line1.KPI.OEE': (k['oee'], D),
        'Line1.KPI.A': (k['A'], D), 'Line1.KPI.P': (k['P'], D), 'Line1.KPI.Q': (k['Q'], D),
        'Line1.KPI.OEE_10min': (k['oee_win']['oee'], D),
        'Line1.KPI.S2Unplanned_s': (k['down_s']['S2']['unplanned'], D),
        'Line1.KPI.S2Planned_s': (k['down_s']['S2']['planned'], D),
        'Line1.S2.Force': (s['stations']['S2']['force'], D), 'Line1.S2.Wear': (s['stations']['S2']['wear'], D),
        'Line1.S2.Health': (k['s2']['health'], D), 'Line1.S2.CyclesToFault': (k['s2']['cycles_to_fault'], D),
        'Line1.S2.ToolOK': (m['tool_ok'], B),
        'Line1.S2.MaintenanceRemaining_s': (m.get('maintenance_remaining_s'), D),
        'Line1.S2.ToolChangeQueued': (m.get('tool_change_queued', False), B),
        'Line1.Tower.Green': (s['lamp'] == 'GREEN', B), 'Line1.Tower.Amber': (s['lamp'] == 'AMBER', B),
        'Line1.Tower.Red': (s['lamp'] == 'RED', B),
    }
    codes = {a['code'] for a in active}
    for code in ('F001', 'F201', 'F002', 'W202'):
        out[f'Line1.Alarms.{code}'] = (code in codes, B)
    for name, serials in s['buffers'].items():
        out[f'Line1.Buffers.{name}.Count'] = (len(serials), I)
    # Pre-formatted strings for HMI panels (raw numeric nodes above stay unrounded)
    fmt = lambda v, pattern: '—' if v is None else pattern.format(v)
    state = ('E-STOP LATCHED' if m['estop_latched'] else 'FAULT' if any(a['sev'] == 'FAULT' for a in active)
             else 'RUNNING' if s['run'] else 'STOPPED')
    for node, value in (('LineState', state), ('SimTime', fmt(s['t'] / 60, '{:.1f} min')), ('Speed', f"{s['speed']}x"),
                        ('Force', fmt(s['stations']['S2']['force'], '{:.1f} N')),
                        ('Health', fmt(k['s2']['health'] and k['s2']['health'] * 100, '{:.0f} %')),
                        ('CyclesToFault', fmt(k['s2']['cycles_to_fault'], '{:.0f}')),
                        ('Maintenance', fmt(m.get('maintenance_remaining_s') or None, '{:.0f} s')),
                        ('Throughput', fmt(k['th_ph'], '{:.0f} /h')), ('OEE10', fmt(k['oee_win']['oee'] and k['oee_win']['oee'] * 100, '{:.0f} %')),
                        ('Yield', fmt(k['Q'] and k['Q'] * 100, '{:.0f} %')), ('LeadTime', fmt(k['lead_s'], '{:.0f} s'))):
        out[f'Line1.Display.{node}'] = (value, S)
    last = m.get('last_decision')
    out['Line1.LastInspection.Serial'] = (last['serial'] if last else '', S)
    out['Line1.LastInspection.Status'] = (last['status'] if last else '', S)
    out['Line1.LastInspection.Codes'] = (' '.join(last['codes']) if last else '', S)
    out['Line1.LastInspection.Pass'] = (bool(last) and last['status'] == 'PASS', B)
    for name in ('In', 'Good', 'Reject', 'WIP', 'Boxes'):
        out[f'Line1.Counts.{name}'] = (s['counts'][name.lower() if name != 'In' else 'in'], I)
    for name, st in s['stations'].items():
        base = f'Line1.Stations.{name}'
        out[f'{base}.State'] = (st['state'], S)
        out[f'{base}.StateCode'] = (STATE_CODES[st['state']], I)
        out[f'{base}.Step'] = (st['step'], S)
        out[f'{base}.Part'] = (st['part'] or '', S)
        out[f'{base}.Cycles'] = (st['cycles'], I)
    plc = m.get('plc') or {'mode': 'internal'}
    out['Line1.PLC.Mode'] = (plc['mode'], S)
    out['Line1.PLC.LinkOK'] = (plc.get('link_ok', False), B)
    coils = plc.get('coils') or {}
    for node, coil in (('Run', 'M_SYS_RUN'), ('LampGreen', 'Q_LAMP_GREEN'), ('LampAmber', 'Q_LAMP_AMBER'),
                       ('LampRed', 'Q_LAMP_RED'), ('Horn', 'Q_HORN'), ('F201', 'F201'), ('F001', 'F001'),
                       ('F002', 'F002'), ('AnyFault', 'M_ANY_FAULT'), ('F201Injected', 'F201_INJECTED'),
                       ('S2Repaired', 'M_S2_REPAIRED')):
        out[f'Line1.PLC.{node}'] = (coils.get(coil), B)
    counters = plc.get('counters') or {}
    for node, key in (('In', 'C_IN'), ('Good', 'C_GOOD'), ('Reject', 'C_REJECT'),
                      ('BoxFill', 'BOX_FILL'), ('Boxes', 'BOXES_TOTAL')):
        out[f'Line1.PLC.Counters.{node}'] = (counters.get(key), I)
    return out


# Writable HMI command nodes -> (command, args); E-stop needs engage and release as separate pulses.
COMMANDS = {'Start': ('start', {}), 'Stop': ('stop', {}), 'Reset': ('reset', {}),
            'EStopEngage': ('estop', {'active': True}), 'EStopRelease': ('estop', {'active': False}),
            'RepairS2': ('repair', {'station': 'S2'}), 'ToolChangeS2': ('tool_change', {'station': 'S2'}),
            'InjectF201': ('inject_fault', {'code': 'F201'})}
HMI_USER = 'HMI (OPC UA)'


class OpcUaServer:
    def __init__(self, endpoint=ENDPOINT, on_command=None):
        self.endpoint = endpoint
        self.on_command = on_command  # callable(cmd, args, user) -> result dict; raises ValueError when refused
        self.latest = None
        self.ready, self.stopping = Event(), Event()
        self.error = None
        self.thread = None

    def start(self):
        self.thread = Thread(target=lambda: asyncio.run(self._main()), name='SyringeTwinOPCUA', daemon=True)
        self.thread.start()
        self.ready.wait(10)

    def close(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=5)

    def publish(self, payload):
        self.latest = flatten(payload)  # one reference swap; the server loop reads it

    async def _main(self):
        logging.getLogger('asyncua').setLevel(logging.WARNING)
        try:
            server = Server()
            await server.init()
            server.set_endpoint(self.endpoint)
            server.set_server_name('SyringeTwin digital twin')
            server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
            idx = await server.register_namespace(NAMESPACE)
            nodes, folders = {}, {}
            objects = server.nodes.objects

            async def ensure(path, vtype):
                if path not in nodes:
                    parent = objects
                    parts = path.split('.')
                    for depth in range(1, len(parts)):
                        key = '.'.join(parts[:depth])
                        if key not in folders:
                            folders[key] = await parent.add_object(ua.NodeId(key, idx), parts[depth - 1])
                        parent = folders[key]
                    nodes[path] = await parent.add_variable(ua.NodeId(path, idx), parts[-1],
                                                            DEFAULTS[vtype], varianttype=vtype)
                return nodes[path]

            commands, speed, result = {}, None, None
            if self.on_command:
                for name in COMMANDS:
                    commands[name] = await ensure(f'Line1.HMI.{name}', B)
                    await commands[name].set_writable()
                speed = await ensure('Line1.HMI.SpeedCmd', I)
                await speed.set_writable()
                result = await ensure('Line1.HMI.LastResult', S)
            published = None
            async with server:
                self.ready.set()
                while not self.stopping.is_set():
                    values = self.latest
                    if values is not None and values is not published:
                        published = values
                        for path, (value, vtype) in values.items():
                            node = await ensure(path, vtype)
                            if value is None:
                                dv = ua.DataValue(ua.Variant(DEFAULTS[vtype], vtype),
                                                  StatusCode=ua.StatusCode(ua.StatusCodes.BadWaitingForInitialData))
                            else:
                                dv = ua.DataValue(ua.Variant(int(value) if vtype is I else value, vtype))
                            await node.write_value(dv)
                    for name, node in commands.items():
                        if await node.read_value():
                            await node.write_value(False)
                            await result.write_value(self._run(*COMMANDS[name]))
                    if speed is not None:
                        x = await speed.read_value()
                        if x:
                            await speed.write_value(ua.Variant(0, I))
                            await result.write_value(self._run('set_speed', {'x': int(x)}))
                    await asyncio.sleep(0.1)
        except Exception as exc:  # report, never take the twin down with it
            self.error = f'{type(exc).__name__}: {exc}'
            self.ready.set()

    def _run(self, cmd, args):
        try:
            return self.on_command(cmd, dict(args), HMI_USER)['message']
        except ValueError as exc:
            return 'Refused: ' + str(exc)

    def status(self):
        return {'endpoint': self.endpoint, 'running': self.thread is not None and self.thread.is_alive(),
                'error': self.error}
