"""One backend owns time; dashboard sessions only read and send commands."""
from collections import deque
from threading import Thread, RLock, Event
from time import monotonic
from .engine import Engine
from .historian import Historian
from .events import wall_time


class Service:
    def __init__(self, data_dir='data', config=None):
        self.engine = Engine(config)
        self.lock, self.closed = RLock(), Event()
        self.thread = None
        self.history = deque(maxlen=300)
        self.historian = Historian(data_dir)
        self.last_error = None
        self.latest = None
        self.sample()

    def start(self):
        self.thread = Thread(target=self.loop, name='SyringeTwinEngine', daemon=True)
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)
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
        k = self.latest['kpi']
        st = self.latest['snapshot']['stations']['S2']
        self.history.append({'t': k['t'], 'throughput': k['th_ph'],
                             'force_N': st['force'], 'oee_pct': k['oee']*100 if k['oee'] is not None else None})
        self.historian.write(self.engine.state, self.latest)

    def command(self, cmd, args, user):
        with self.lock:
            if self.last_error:
                raise ValueError('Engine halted: ' + self.last_error)
            result = self.engine.command(cmd,args,user)
            # Refresh states immediately for the operator's response.
            from .control import scan
            if not self.engine.state.run:
                scan(self.engine.state)
            self.sample()
            return result
