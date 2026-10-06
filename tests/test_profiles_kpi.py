"""Demo profile timeline and the rolling OEE window."""
import pytest
from twin.engine import Engine
from twin.kpi import calculate
from twin.model import load_config


def test_demo_profile_tells_the_story_in_order():
    """Fresh tool -> W202 warning -> R2 rejects -> natural F201, all within ~15 sim-min."""
    e = Engine(load_config('demo'))
    e.command('start', user='QA')
    marks = {}
    while 'F201' not in marks and e.state.t < 1200:
        e.tick()
        s = e.state
        if 'W202' not in marks and any(a['code'] == 'W202' for a in s.alarms):
            marks['W202'] = s.t
        if 'R2' not in marks and s.pareto.get('R2'):
            marks['R2'] = s.t
        if s.faults_s2:
            marks['F201'] = s.t
    assert 300 < marks['W202'] < marks['R2'] < marks['F201'] < 1200
    assert e.payload()['meta']['profile'].startswith('Demo profile')


def test_default_config_has_no_profile_label():
    assert Engine().payload()['meta']['profile'] is None


def test_unknown_profile_rejected():
    with pytest.raises(ValueError):
        load_config('nope')


def test_rolling_oee_recovers_after_a_fault_while_cumulative_stays_low():
    e = Engine(load_config('demo'))
    e.command('start', user='QA')
    while not e.state.faults_s2:
        e.tick()
    e.advance(900)  # unattended: S2 stays faulted
    assert calculate(e.state)['oee_win']['A'] < 0.2
    e.command('repair', {'station': 'S2'}, 'QA')
    e.advance(91)
    e.command('reset', {}, 'QA')
    e.command('tool_change', {'station': 'S2'}, 'QA')
    e.advance(700)
    k = calculate(e.state)
    assert k['oee_win']['A'] > 0.95
    assert k['oee_win']['oee'] > k['oee'] + 0.2
