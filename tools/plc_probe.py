"""OpenPLC connection test for plc/openplc/spike.st (docs/plc/PLC_SPEC.md section 7).

Usage: python tools/plc_probe.py [--host 127.0.0.1] [--port 502]
Exit code 0 only when every check passes.
"""
import argparse
import sys
import time
from pymodbus.client import ModbusTcpClient

MW = 1024  # %MW0 is holding register 1024 in OpenPLC v3


def check(name, ok, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=502)
    args = parser.parse_args()
    client = ModbusTcpClient(args.host, port=args.port, timeout=2)
    if not client.connect():
        print(f'[FAIL] connect: no Modbus server at {args.host}:{args.port}. '
              'Is the PLC running and the Modbus server enabled in Settings?')
        return 1
    results = []
    try:
        client.write_register(MW + 0, 41)
        client.write_register(MW + 1, 1)
        time.sleep(0.2)
        value = client.read_holding_registers(0, count=1).registers[0]
        results.append(check('holding registers (%MW0 -> %QW0)', value == 42, f'wrote 41, read {value}'))
        coil = client.read_coils(0, count=1).bits[0]
        results.append(check('coils (%MW1 -> %QX0.0)', coil is True, f'read {coil}'))
        client.write_register(MW + 1, 0)
        time.sleep(0.2)
        coil = client.read_coils(0, count=1).bits[0]
        results.append(check('coil clears', coil is False, f'read {coil}'))

        first = client.read_holding_registers(1, count=1).registers[0]
        start = time.perf_counter()
        time.sleep(1.0)
        second = client.read_holding_registers(1, count=1).registers[0]
        rate = ((second - first) % 30001) / (time.perf_counter() - start)
        results.append(check('scan rate (%QW1)', 40 <= rate <= 55, f'{rate:.1f} scans/s (20 ms task = 50)'))

        samples = []
        for _ in range(50):
            t0 = time.perf_counter()
            client.read_holding_registers(0, count=2)
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        p95 = samples[int(len(samples) * 0.95) - 1]
        results.append(check('round trip', p95 < 10, f'median {samples[25]:.1f} ms, p95 {p95:.1f} ms'))
    finally:
        client.close()
    ok = all(results)
    print('GO: OpenPLC path confirmed.' if ok else 'NO-GO: see failures above.')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
