"""Acceptance evidence for the rebuilt dashboard MVP, not full PLC certification."""
import json
from copy import deepcopy
import pytest
from twin.engine import Engine
from twin.model import load_config
from twin.kpi import calculate, counts, pallet_check


def perfect_config():
    c = load_config()
    c['stations']['S2'].update(initial_wear=0,wear_per_cycle=0)
    c['stations']['S2']['force']['sigma'] = 0
    c['stations']['S1']['print_sigma'] = 0
    c['stations']['S3']['cap_probability'] = 1
    c['stations']['S3']['mark_probabilities'] = [1,0,0,0]
    c['stations']['S4']['leak_sigma'] = 0
    return c


def running(config=None):
    e = Engine(config)
    e.command('start')
    return e


def test_every_tick_conserves_parts_and_unique_pallets():
    e = running()
    for _ in range(10000):
        e.tick()
        c = counts(e.state)
        assert c['in'] == c['good']+c['reject']+c['wip']
        assert c['wip'] <= 10
        assert pallet_check(e.state)


def test_rate_and_littles_law_same_window():
    e = running(perfect_config())
    e.advance(300)
    before = e.state.counts['good']
    integral = e.state.wip_integral
    e.advance(3600)
    completed = [row for row in e.state.completions if 300 < row[0] <= 3900]
    good = e.state.counts['good']-before
    assert 342 <= good <= 378
    wip = (e.state.wip_integral-integral)/3600
    lead = sum(row[1] for row in completed)/len(completed)
    error = abs(wip-len(completed)/3600*lead)/wip
    assert error < 0.1


def test_seed_determinism():
    a,b = running(),running()
    a.advance(1000)
    b.advance(1000)
    assert a.state.counts==b.state.counts
    assert a.state.stations['S2'].force==b.state.stations['S2'].force


def test_stop_preserves_all_process_progress():
    e = running()
    e.advance(25)
    e.command('stop')
    before = deepcopy((e.state.pallets,e.state.buffers,e.state.transfers,e.state.counts))
    e.advance(30)
    assert before==(e.state.pallets,e.state.buffers,e.state.transfers,e.state.counts)
    assert all(s.state=='STOPPED' for s in e.state.stations.values())


def test_estop_requires_release_reset_start():
    e = running()
    e.advance(25)
    e.command('estop',{'active':True})
    e.command('reset')
    assert e.state.estop_latched and not e.state.run
    with pytest.raises(ValueError): e.command('start')
    e.command('estop',{'active':False})
    with pytest.raises(ValueError): e.command('start')
    e.command('reset')
    assert not e.state.run
    e.command('start')
    assert e.state.run


def test_fault_local_ripple_repair_and_reject_trace():
    e = running(perfect_config())
    e.advance(150)
    while e.state.stations['S2'].step_i != 1:
        e.tick()
    serial = e.state.pallets[e.state.stations['S2'].pallet]
    e.command('inject_fault',{'code':'F201'})
    assert e.state.run
    e.command('reset')
    assert e.state.stations['S2'].fault=='F201'
    e.advance(30)
    assert e.state.stations['S1'].state=='BLOCKED'
    assert e.state.stations['S3'].state=='STARVED'
    e.command('repair',{'station':'S2'})
    e.advance(89)
    assert not e.state.stations['S2'].tool_ok
    e.command('reset')
    assert e.state.stations['S2'].fault=='F201'
    e.advance(1.1)
    assert e.state.stations['S2'].tool_ok
    e.command('reset')
    assert e.state.stations['S2'].step_i==2
    e.advance(100)
    assert e.state.parts[serial].status=='FAIL'
    assert 'R2' in e.state.parts[serial].reject_codes
    assert e.state.parts[serial].t_out is not None
    assert any(ev.get('injected') for ev in e.state.parts[serial].events)


def test_bin_refill_delay_and_recovery():
    e = running(perfect_config())
    e.state.bins['hopper']=0
    e.advance(10)
    assert e.state.counts['in']==0
    assert e.state.bins['hopper']==0
    e.advance(25)
    assert e.state.counts['in']>0
    assert e.state.bins['hopper']>0


def test_planned_tool_change_waits_for_cycle_boundary():
    e = running()
    e.advance(30)
    st = e.state.stations['S2']
    e.command('tool_change',{'station':'S2'})
    assert st.pending_tool_change
    e.advance(40)
    assert st.wear < 0.04
    assert st.planned >= 19.9
    assert st.unplanned==0


def test_payload_nulls_and_kpi_edges_are_valid_json():
    e = Engine()
    assert calculate(e.state)['oee'] is None
    assert calculate(e.state)['lead_s'] is None
    json.dumps(e.payload(),allow_nan=False)
    e.command('start')
    e.advance(100)
    assert calculate(e.state)['line_ct_s']>0
    json.dumps(e.payload(),allow_nan=False)


@pytest.mark.parametrize('cmd,args',[
    ('set_speed',{'x':3}),('estop',{'active':'false'}),
    ('repair',{'station':'S3'}),('refill',{'bin':'unknown'}),
    ('inject_fault',{'code':'F101'}),('unknown',{})])
def test_bad_commands_rejected(cmd,args):
    with pytest.raises(ValueError): Engine().command(cmd,args)


def test_operator_is_required_and_commands_are_audited():
    e = Engine()
    with pytest.raises(ValueError): e.command('start',user=' ')
    e.command('start',user='Aryan')
    assert e.state.commands[-1]['user']=='Aryan'
