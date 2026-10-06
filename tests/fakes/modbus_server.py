"""Minimal Modbus TCP server used as a test double for OpenPLC Runtime.

Implements function codes 1, 3, 5, 6, 15 and 16 over one address space that
mirrors OpenPLC v3: coils (%QX) and holding registers 0-2047 (%QW, then %MW
from 1024). A `logic(server)` callback runs every `scan_s`, like a PLC task.
It exists only so the bridge and probe can be tested without OpenPLC.
"""
import socket
import struct
import threading
import time


class ModbusServer:
    def __init__(self, logic=None, host='127.0.0.1', port=0, scan_s=0.02):
        self.coils = [False] * 800
        self.hr = [0] * 2048
        self.lock = threading.Lock()
        self.logic, self.scan_s = logic, scan_s
        self.sock = socket.create_server((host, port))
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.scanning = True
        threading.Thread(target=self._accept, daemon=True).start()
        if scan_s:
            threading.Thread(target=self._scan, daemon=True).start()

    def close(self):
        self.running = False
        self.sock.close()

    def scan_once(self):
        with self.lock:
            self.logic(self)

    def _scan(self):
        while self.running:
            if self.logic and self.scanning:
                with self.lock:
                    self.logic(self)
            time.sleep(self.scan_s)

    def _accept(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            while self.running:
                header = self._read(conn, 7)
                if not header:
                    return
                tid, pid, length, unit = struct.unpack('>HHHB', header)
                pdu = self._read(conn, length - 1)
                if pdu is None:
                    return
                with self.lock:
                    reply = self._handle(pdu)
                conn.sendall(struct.pack('>HHHB', tid, pid, len(reply) + 1, unit) + reply)

    @staticmethod
    def _read(conn, n):
        data = b''
        while len(data) < n:
            try:
                chunk = conn.recv(n - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def _handle(self, pdu):
        fc = pdu[0]
        if fc == 1:
            start, count = struct.unpack('>HH', pdu[1:5])
            bits = self.coils[start:start + count]
            data = bytearray((count + 7) // 8)
            for i, bit in enumerate(bits):
                data[i // 8] |= bit << (i % 8)
            return bytes([fc, len(data)]) + bytes(data)
        if fc == 3:
            start, count = struct.unpack('>HH', pdu[1:5])
            values = [v & 0xFFFF for v in self.hr[start:start + count]]
            return bytes([fc, 2 * count]) + struct.pack(f'>{count}H', *values)
        if fc == 5:
            address, value = struct.unpack('>HH', pdu[1:5])
            self.coils[address] = value == 0xFF00
            return pdu[:5]
        if fc == 6:
            address, value = struct.unpack('>HH', pdu[1:5])
            self.hr[address] = value
            return pdu[:5]
        if fc == 15:
            start, count = struct.unpack('>HH', pdu[1:5])
            for i in range(count):
                self.coils[start + i] = bool(pdu[6 + i // 8] >> (i % 8) & 1)
            return pdu[:5]
        if fc == 16:
            start, count = struct.unpack('>HH', pdu[1:5])
            self.hr[start:start + count] = struct.unpack(f'>{count}H', pdu[6:6 + 2 * count])
            return pdu[:5]
        return bytes([fc | 0x80, 1])


def spike_logic(server):
    """Same behaviour as plc/openplc/spike.st."""
    server.hr[0] = (server.hr[1024] + 1) & 0xFFFF
    server.coils[0] = server.hr[1025] != 0
    server.hr[1] = 0 if server.hr[1] >= 30000 else server.hr[1] + 1


if __name__ == '__main__':
    srv = ModbusServer(spike_logic, port=5020)
    print(f'Spike double listening on 127.0.0.1:{srv.port}')
    while True:
        time.sleep(1)
