"""Acceptance test PLC-01..PLC-13 against a running PLC (docs/plc/PLC_SPEC.md section 6).

Usage: python tools/plc_acceptance.py [--host 127.0.0.1] [--port 502] [--label "OpenPLC Runtime v3"]
Load plc/openplc/syringetwin.st into OpenPLC Runtime and start it first.
The script plays the twin's role directly over Modbus TCP, so each rung is
checked in isolation. Results go to docs/evidence/plc_manual_results.json,
which tools/validation_matrix.py merges into the test matrix.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
import time
from pymodbus.client import ModbusTcpClient

ROOT = Path(__file__).resolve().parents[1]
MW = 1024
INPUTS = ('CMD_START', 'CMD_STOP', 'CMD_RESET', 'I_ESTOP_OK', 'I_S2_TOOL_OK', 'AI_S2_FORCE',
          'S2_PRESS_SEQ', 'GOOD_SEQ', 'REJECT_SEQ', 'HEARTBEAT', 'TWIN_WARN', 'ANY_BLOCKED',
          'S2_DONE', 'B3_ROOM', 'IN_SEQ', 'CMD_INJECT_F201')
COILS = ('M_SYS_RUN', 'Q_LAMP_GREEN', 'Q_LAMP_AMBER', 'Q_LAMP_RED', 'Q_HORN', 'F201', 'F001',
         'F002', 'M_ANY_FAULT', 'F201_INJECTED', 'S2_RELEASE_PERMIT', 'M_S2_REPAIRED')
REGISTERS = ('S2_VERDICT_SEQ', 'PLC_HEARTBEAT', 'C_IN', 'C_GOOD', 'C_REJECT', 'BOX_FILL', 'BOXES_TOTAL')
SETTLE = 0.15  # >= 7 scans at 20 ms


class Plc:
    def __init__(self, host, port):
        self.client = ModbusTcpClient(host, port=port, timeout=2)
        if not self.client.connect():
            raise SystemExit(f'No Modbus server at {host}:{port}. Start the PLC and enable Modbus in Settings.')
        self.lock = threading.Lock()
        self.heartbeat, self.frozen, self.stop = 0, False, False
        threading.Thread(target=self._beat, daemon=True).start()

    def _beat(self):
        """The twin's heartbeat (%MW9), so the PLC watchdog stays healthy unless a test freezes it."""
        while not self.stop:
            if not self.frozen:
                self.heartbeat = (self.heartbeat + 1) % 32768
                self.write('HEARTBEAT', self.heartbeat)
            time.sleep(0.05)

    def write(self, name, value):
        with self.lock:
            self.client.write_register(MW + INPUTS.index(name), int(value) & 0xFFFF)

    def read(self, name):
        with self.lock:
            return self.client.read_holding_registers(MW + INPUTS.index(name), count=1).registers[0]

    def coils(self):
        with self.lock:
            return dict(zip(COILS, self.client.read_coils(0, count=len(COILS)).bits))

    def regs(self):
        with self.lock:
            return dict(zip(REGISTERS, self.client.read_holding_registers(0, count=len(REGISTERS)).registers))

    def pulse(self, name):
        self.write(name, 1)
        time.sleep(0.2)
        self.write(name, 0)
        time.sleep(SETTLE)

    def bump(self, name):
        self.write(name, (self.read(name) + 1) % 32768)
        time.sleep(SETTLE)

    def clean_slate(self):
        """Healthy inputs, any latched faults cleared, line stopped."""
        for name in INPUTS:
            if name != 'HEARTBEAT':
                self.write(name, 0)
        self.write('I_ESTOP_OK', 1)
        time.sleep(SETTLE)
        self.write('I_S2_TOOL_OK', 1)  # rising edge acknowledges any latched F201
        time.sleep(SETTLE)
        self.pulse('CMD_RESET')
        self.pulse('CMD_STOP')

    def close(self):
        self.stop = True
        time.sleep(0.1)
        self.client.close()


def run(plc):
    results = {}

    def record(cid, ok, actual):
        results[cid] = {'result': 'PASS' if ok else 'FAIL', 'actual': actual}
        print(f"[{'PASS' if ok else 'FAIL'}] {cid}: {actual}")

    plc.clean_slate()
    c = plc.coils()
    if c['F001'] or c['F201'] or c['F002']:
        print('Warning: faults still latched after clean slate:', {k: c[k] for k in ('F001', 'F201', 'F002')})

    plc.pulse('CMD_START')
    c = plc.coils()
    record('PLC-01', c['M_SYS_RUN'] and c['Q_LAMP_GREEN'], f"run {c['M_SYS_RUN']}, green {c['Q_LAMP_GREEN']}")

    plc.pulse('CMD_STOP')
    c = plc.coils()
    record('PLC-02', not c['M_SYS_RUN'] and not c['Q_LAMP_GREEN'] and not c['M_ANY_FAULT'],
           f"run {c['M_SYS_RUN']}, green {c['Q_LAMP_GREEN']}, any fault {c['M_ANY_FAULT']}")

    plc.pulse('CMD_START')
    plc.write('I_ESTOP_OK', 0)
    reds = []
    end = time.time() + 1.6
    while time.time() < end:
        reds.append(plc.coils()['Q_LAMP_RED'])
        time.sleep(0.05)
    c = plc.coils()
    flashing = True in reds and False in reds
    record('PLC-03', c['F001'] and not c['M_SYS_RUN'] and c['Q_HORN'] and flashing,
           f"F001 {c['F001']}, run {c['M_SYS_RUN']}, horn {c['Q_HORN']}, red lamp flashing {flashing}")

    plc.pulse('CMD_RESET')
    c = plc.coils()
    record('PLC-04', c['F001'], f"F001 after Reset with E-stop open: {c['F001']}")

    plc.write('I_ESTOP_OK', 1)
    time.sleep(SETTLE)
    plc.pulse('CMD_RESET')
    cleared = not plc.coils()['F001']
    plc.pulse('CMD_START')
    c = plc.coils()
    record('PLC-05', cleared and c['M_SYS_RUN'], f"F001 cleared {cleared}, run after Start {c['M_SYS_RUN']}")

    plc.write('AI_S2_FORCE', 1450)
    plc.bump('S2_PRESS_SEQ')
    c, r, seq = plc.coils(), plc.regs(), plc.read('S2_PRESS_SEQ')
    record('PLC-06', not c['F201'] and r['S2_VERDICT_SEQ'] == seq,
           f"force 145.0 N: F201 {c['F201']}, verdict {r['S2_VERDICT_SEQ']} = sample {seq}")

    plc.write('AI_S2_FORCE', 1612)
    plc.bump('S2_PRESS_SEQ')
    c, r, seq = plc.coils(), plc.regs(), plc.read('S2_PRESS_SEQ')
    record('PLC-07', c['F201'] and c['M_SYS_RUN'] and r['S2_VERDICT_SEQ'] == seq,
           f"force 161.2 N: F201 {c['F201']}, run still {c['M_SYS_RUN']}, verdict echoed {r['S2_VERDICT_SEQ'] == seq}")

    plc.pulse('CMD_RESET')
    c = plc.coils()
    record('PLC-08', c['F201'] and not c['M_S2_REPAIRED'], f"F201 after Reset without repair: {c['F201']}")

    plc.write('I_S2_TOOL_OK', 0)
    time.sleep(SETTLE)
    plc.write('I_S2_TOOL_OK', 1)
    time.sleep(SETTLE)
    repaired = plc.coils()['M_S2_REPAIRED']
    plc.pulse('CMD_RESET')
    c = plc.coils()
    record('PLC-09', repaired and not c['F201'], f"repair acknowledged {repaired}, F201 after Reset {c['F201']}")

    before = plc.regs()
    for _ in range(10):
        plc.bump('GOOD_SEQ')
    for _ in range(2):
        plc.bump('REJECT_SEQ')
    after = plc.regs()
    good = (after['C_GOOD'] - before['C_GOOD']) % 65536
    reject = (after['C_REJECT'] - before['C_REJECT']) % 65536
    boxes = (after['BOXES_TOTAL'] - before['BOXES_TOTAL']) % 65536
    record('PLC-10', good == 10 and reject == 2 and boxes == 1 and after['BOX_FILL'] == before['BOX_FILL'],
           f"+{good} good, +{reject} reject, +{boxes} box, box fill {before['BOX_FILL']} → {after['BOX_FILL']}")

    plc.frozen = True
    time.sleep(1.5)
    c = plc.coils()
    record('PLC-11', c['F002'] and not c['M_SYS_RUN'], f"heartbeat frozen 1.5 s: F002 {c['F002']}, run {c['M_SYS_RUN']}")

    plc.frozen = False
    time.sleep(0.3)
    plc.pulse('CMD_RESET')
    cleared = not plc.coils()['F002']
    plc.pulse('CMD_START')
    c = plc.coils()
    record('PLC-12', cleared and c['M_SYS_RUN'], f"F002 cleared {cleared}, run after Start {c['M_SYS_RUN']}")

    plc.write('TWIN_WARN', 1)
    time.sleep(SETTLE)
    c = plc.coils()
    plc.write('TWIN_WARN', 0)
    record('PLC-13', c['Q_LAMP_AMBER'] and not c['Q_LAMP_GREEN'] and not c['M_ANY_FAULT'],
           f"amber {c['Q_LAMP_AMBER']}, green {c['Q_LAMP_GREEN']}")

    plc.clean_slate()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=502)
    parser.add_argument('--label', default='OpenPLC Runtime v3')
    parser.add_argument('--no-save', action='store_true', help='print results only')
    args = parser.parse_args()
    plc = Plc(args.host, args.port)
    try:
        results = run(plc)
    finally:
        plc.close()
    stamp = datetime.now().astimezone().isoformat(timespec='seconds')
    for row in results.values():
        row['actual'] = f"{row['actual']} ({args.label}, {stamp})"
    passed = sum(r['result'] == 'PASS' for r in results.values())
    print(f'{passed}/{len(results)} PLC acceptance cases PASS on {args.label} at {args.host}:{args.port}')
    if not args.no_save:
        path = ROOT / 'docs' / 'evidence' / 'plc_manual_results.json'
        path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
        print('Saved', path.relative_to(ROOT), '— now run: python tools/validation_matrix.py')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
