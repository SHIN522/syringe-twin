"""Plain simulation state, following brief sections 3, 4 and 8."""
from dataclasses import dataclass, field
from collections import deque
from pathlib import Path
import numpy as np
import yaml

STATIONS = ('IN', 'S1', 'S2', 'S3', 'S4', 'OUT')


def load_config():
    path = Path(__file__).resolve().parents[1] / 'config' / 'line.yaml'
    return yaml.safe_load(path.read_text())


@dataclass
class Part:
    serial: str
    t_in: float
    t_out: float | None = None
    status: str = 'WIP'
    meas: dict = field(default_factory=dict)
    reject_codes: list = field(default_factory=list)
    events: list = field(default_factory=list)


@dataclass
class Station:
    pallet: int | None = None
    step_i: int = -1
    elapsed: float = 0.0
    done: bool = False
    cycle_start: float = 0.0
    cycles: int = 0
    last_ct: float | None = None
    cycle_times: deque = field(default_factory=lambda: deque(maxlen=20))
    fault: str | None = None
    tool_ok: bool = True
    maintenance: str | None = None
    remaining: float = 0.0
    pending_tool_change: bool = False
    wear: float = 0.0
    force: float | None = None
    forces: deque = field(default_factory=lambda: deque(maxlen=30))
    unplanned: float = 0.0
    planned: float = 0.0
    state: str = 'STOPPED'
    reason: str | None = None


@dataclass
class Transfer:
    pallet: int
    source: str
    destination: str
    remaining: float
    total: float


@dataclass
class State:
    config: dict
    t: float = 0.0
    run: bool = False
    estop_active: bool = False
    estop_latched: bool = False
    speed: int = 10
    stations: dict = field(default_factory=dict)
    buffers: dict = field(default_factory=dict)
    pallets: dict = field(default_factory=dict)
    empty: list = field(default_factory=list)
    transfers: list = field(default_factory=list)
    parts: dict = field(default_factory=dict)
    bins: dict = field(default_factory=dict)
    refills: dict = field(default_factory=dict)
    counts: dict = field(default_factory=lambda: {'in': 0, 'good': 0, 'reject': 0})
    alarms: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    events: deque = field(default_factory=lambda: deque(maxlen=200))
    completions: list = field(default_factory=list)
    good_exits: list = field(default_factory=list)
    decisions: int = 0
    passes: int = 0
    pareto: dict = field(default_factory=dict)
    planned_time: float = 0.0
    faults_s2: int = 0
    wip_integral: float = 0.0
    rng: dict = field(default_factory=dict)
    revision: int = 0


def new_state(config=None):
    c = load_config() if config is None else config
    s = State(config=c)
    s.stations = {name: Station() for name in STATIONS}
    s.stations['S2'].wear = c['stations']['S2']['initial_wear']
    s.buffers = {name: [] for name in c['buffers']}
    s.bins = dict(c['bins'])
    s.pallets = {i: None for i in range(1, c['pallets'] + 1)}
    s.empty = list(s.pallets)
    s.rng = {name: np.random.default_rng(c['seed'] + i)
             for i, name in enumerate(STATIONS)}
    return s
