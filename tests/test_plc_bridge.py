"""PLC mode: the twin controlled over real Modbus TCP by a stand-in of syringetwin.st."""
import pytest
from twin.engine import Engine
from twin.model import load_config
from twin.plc_bridge import PlcBridge
from fakes.modbus_server import ModbusServer
from fakes.softplc import SoftPlc, COILS


class Rig:
    """One step = 20 ms wall: 2 twin ticks (10×), one bridge exchange, one PLC scan."""

    def __init__(self, config=None):
        self.plc = SoftPlc()
        self.server = ModbusServer(self.plc, scan_s=None)
        self.now = 0.0
        self.bridge = PlcBridge('127.0.0.1', self.server.port, clock=lambda: self.now)
        self.engine = Engine(config)
        self.s = self.engine.state
        self.bridge.attach(self.s)
        self.plc_running = True
        self.step(5)

    def step(self, n=1, ticks=2):
        for _ in range(n):
            for _ in range(ticks):
                self.engine.tick()
            self.bridge.exchange(self.s)
            if self.plc_running:
                self.server.scan_once()
            self.now += 0.02

    def until(self, condition, limit_s=600):
        for _ in range(int(limit_s / 0.2)):
            if condition():
                return
            self.step()
        raise AssertionError('condition not reached')

    def cmd(self, cmd, args=None):
        return self.bridge.command(self.s, cmd, args or {}, 'QA')

    def coil(self, name):
        return self.server.coils[COILS.index(name)]

    def alarms(self):
        return {a['code'] for a in self.s.alarms if a['t_cleared'] is None}


@pytest.fixture
def rig():
    r = Rig()
    yield r
    r.bridge.close()
    r.server.close()


def worn_config():
    c = load_config()
    c['stations']['S2']['initial_wear'] = 0.95
    return c


def test_start_and_stop_go_through_the_plc(rig):
    assert rig.bridge.link_ok and not rig.s.run
    rig.cmd('start')
    assert not rig.s.run  # the twin waits for the PLC's run permissive
    rig.step(15)
    assert rig.coil('M_SYS_RUN') and rig.s.run and rig.coil('Q_LAMP_GREEN')
    rig.step(1500)
    assert rig.s.counts['good'] > 0
    rig.cmd('stop')
    rig.step(15)
    assert not rig.coil('M_SYS_RUN') and not rig.s.run
    assert rig.s.commands[-1]['result'].startswith('Stop sent to PLC')


def test_estop_latch_needs_release_reset_start(rig):
    rig.cmd('start')
    rig.step(15)
    rig.cmd('estop', {'active': True})
    assert not rig.s.run
    rig.step(5)
    assert rig.coil('F001') and rig.s.estop_latched and 'F001' in rig.alarms()
    rig.cmd('reset')
    rig.step(15)
    assert rig.coil('F001')
    with pytest.raises(ValueError):
        rig.cmd('start')
    rig.cmd('estop', {'active': False})
    rig.step(5)
    with pytest.raises(ValueError):
        rig.cmd('start')
    rig.cmd('reset')
    rig.step(15)
    assert not rig.coil('F001') and 'F001' not in rig.alarms()
    rig.cmd('start')
    rig.step(15)
    assert rig.s.run


def test_plc_detects_overload_and_controls_recovery():
    r = Rig(worn_config())
    try:
        r.cmd('start')
        r.until(lambda: r.coil('F201'))
        r.step(2)
        st = r.s.stations['S2']
        serial = r.s.pallets[st.pallet]
        assert st.fault == 'F201' and st.force > 160
        assert r.coil('M_SYS_RUN') and r.s.run  # local fault: the line keeps running (D1)
        r.step(150)  # 30 sim-s
        assert r.s.stations['S1'].state == 'BLOCKED'
        assert r.s.stations['S3'].state == 'STARVED'
        r.cmd('reset')
        r.step(15)
        assert r.coil('F201')  # no reset before the repair
        r.cmd('repair', {'station': 'S2'})
        r.until(lambda: st.tool_ok, 120)
        r.step(5)
        assert r.coil('M_S2_REPAIRED')
        r.cmd('reset')
        r.step(15)
        assert not r.coil('F201') and st.fault is None and 'F201' not in r.alarms()
        r.until(lambda: r.s.parts[serial].t_out is not None, 200)
        assert 'R2' in r.s.parts[serial].reject_codes
    finally:
        r.bridge.close()
        r.server.close()


def test_every_press_waits_for_the_plc_verdict(rig):
    rig.cmd('start')
    rig.step(15)
    st = rig.s.stations['S2']
    rig.until(lambda: st.press_samples >= 3 and st.step_i == 0 and not st.done and st.elapsed >= 1.5)
    samples = st.press_samples
    rig.plc_running = False  # no PLC scan: no verdict for the coming sample
    rig.step(10)  # 0.2 s wall, inside the 1 s watchdog
    assert st.press_samples == samples + 1
    assert st.step_i == 0 and st.done and not rig.bridge.link_fault
    rig.plc_running = True
    rig.step(3)
    assert st.step_i == 1  # INSERT starts once the PLC has evaluated the force


def test_injected_fault_is_marked(rig):
    rig.cmd('start')
    rig.step(15)
    st = rig.s.stations['S2']
    rig.until(lambda: st.pallet is not None and st.step_i == 1 and not st.done)
    serial = rig.s.pallets[st.pallet]
    rig.cmd('inject_fault', {'code': 'F201'})
    rig.step(15)
    assert rig.coil('F201') and rig.coil('F201_INJECTED') and st.fault == 'F201'
    assert any(ev.get('injected') for ev in rig.s.parts[serial].events)


def test_link_loss_stops_the_line_and_needs_reset(rig):
    rig.cmd('start')
    rig.step(15)
    rig.plc_running = False
    rig.step(60)  # 1.2 s without a PLC heartbeat
    assert not rig.s.run and 'F002' in rig.alarms()
    rig.plc_running = True
    rig.step(60)
    assert rig.bridge.link_ok and not rig.s.run
    with pytest.raises(ValueError):
        rig.cmd('start')
    rig.cmd('reset')
    rig.step(15)
    assert 'F002' not in rig.alarms()
    rig.cmd('start')
    rig.step(15)
    assert rig.s.run


def test_plc_counters_match_the_twin(rig):
    rig.cmd('start')
    rig.step(3000)  # 600 sim-s
    status = rig.bridge.status(rig.s)
    assert rig.s.counts['good'] > 20
    assert status['counters_consistent'] is True
    assert status['counters']['BOXES_TOTAL'] * 10 + status['counters']['BOX_FILL'] == status['counters']['C_GOOD']


def test_speed_limited_in_plc_mode(rig):
    with pytest.raises(ValueError):
        rig.cmd('set_speed', {'x': 50})
    rig.cmd('set_speed', {'x': 5})
    assert rig.s.speed == 5
