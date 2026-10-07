"""One backend owns time; dashboard sessions only read and send commands."""
from collections import deque
from threading import Thread, RLock, Event
from time import monotonic
from .engine import Engine
from .historian import Historian
from .events import wall_time


class Service:
    def __init__(self, data_dir='data', config=None, plc=None, opcua=None):
        self.engine = Engine(config)
        self.opcua = opcua  # OpcUaServer, or None when OPC UA is disabled
        if opcua is not None and opcua.on_command is None:
            opcua.on_command = self.command  # HMI writes run the same audited command path
        self.bridge = plc  # PlcBridge in PLC mode, None in internal mode
        if plc:
            plc.attach(self.engine.state)
        self.lock, self.closed = RLock(), Event()
        self.thread = None
        self.history = deque(maxlen=300)
        self.historian = Historian(data_dir)
        self.last_error = None
        self.latest = None
        self.sample()

    def start(self):
        if self.opcua:
            self.opcua.start()
        self.thread = Thread(target=self.loop, name='SyringeTwinEngine', daemon=True)
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.bridge:
            self.bridge.close()
        if self.opcua:
            self.opcua.close()
        with self.lock:
            self.sample()

    def loop(self):
        last, credit, sampled = monotonic(), 0.0, monotonic()
        try:
            while not self.closed.is_set():
                now = monotonic()
                with self.lock:
                    s = self.engine.state
                    credit += min(now-last, 0.5) * s.speed
                    while credit >= s.config['dt']:
                        self.engine.tick()
                        credit -= s.config['dt']
                    if self.bridge:
                        self.bridge.exchange(s)
                    if now - sampled >= 0.5:
                        self.sample()
                        sampled = now
                last = now
                self.closed.wait(0.02)
        except Exception as exc:
            with self.lock:
                self.last_error = f'{type(exc).__name__}: {exc}'
                self.engine.state.run = False

    def sample(self):
        self.latest = self.engine.payload()
        self.latest['meta']['published_wall'] = wall_time()
        self.latest['meta']['database'] = self.historian.path.name
        self.latest['meta']['plc'] = (self.bridge.status(self.engine.state) if self.bridge
                                      else {'mode': 'internal'})
        self.latest['meta']['opcua'] = self.opcua.status() if self.opcua else None
        decided = [p for p in self.engine.state.parts.values() if p.status != 'WIP']
        last = max(decided, key=lambda p: p.t_out or 0, default=None)
        self.latest['meta']['last_decision'] = None if last is None else {
            'serial': last.serial, 'status': last.status, 'codes': last.reject_codes}
        if self.opcua:
            self.opcua.publish(self.latest)
        k = self.latest['kpi']
        st = self.latest['snapshot']['stations']['S2']
        self.history.append({'t': k['t'], 'throughput': k['th_ph'],
                             'force_N': st['force'], 'oee_pct': k['oee']*100 if k['oee'] is not None else None,
                             'oee_win_pct': k['oee_win']['oee']*100 if k['oee_win']['oee'] is not None else None})
        self.historian.write(self.engine.state, self.latest)

    def command(self, cmd, args, user):
        with self.lock:
            if self.last_error:
                raise ValueError('Engine halted: ' + self.last_error)
            if self.bridge:
                result = self.bridge.command(self.engine.state, cmd, args, user)
            else:
                result = self.engine.command(cmd,args,user)
            # Refresh states immediately for the operator's response.
            from .control import scan
            if not self.engine.state.run:
                scan(self.engine.state)
            self.sample()
            return result
