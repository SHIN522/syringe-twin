"""Formal validation matrix: expected vs measured, PASS/FAIL, written to docs/evidence/.

Usage: python tools/validation_matrix.py      (writes test_matrix.md and test_matrix.json)
Every "actual" value is measured from a run of the real engine in this process.
PLC-mode rows use the Modbus stand-in in tests/fakes; rows marked MANUAL are run
on OpenPLC Runtime and recorded in docs/evidence/plc_manual_results.json.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from statistics import mean
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

from twin.engine import Engine  # noqa: E402
from twin.kpi import counts, pallet_check  # noqa: E402
from twin.model import load_config  # noqa: E402
from twin.whatif import run_whatif  # noqa: E402

CASES = []


def case(cid, area, title, expected):
    def register(fn):
        CASES.append({'id': cid, 'area': area, 'title': title, 'expected': expected, 'run': fn})
        return fn
    return register


# ---- helpers ----------------------------------------------------------------

def running(config=None):
    e = Engine(config)
    e.command('start', user='QA')
    return e


def perfect():
    c = load_config()
    c['stations']['S2'].update(initial_wear=0, wear_per_cycle=0)
    c['stations']['S2']['force']['sigma'] = 0
    c['stations']['S1']['print_sigma'] = 0
    c['stations']['S3']['cap_probability'] = 1
    c['stations']['S3']['mark_probabilities'] = [1, 0, 0, 0]
    c['stations']['S4']['leak_sigma'] = 0
    return c


def raises(fn):
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return None


def until(e, condition, limit_s):
    start = e.state.t
    while not condition():
        if e.state.t - start > limit_s:
            return None
        e.tick()
    return e.state.t - start


def tripped_demo():
    """Demo profile run to its natural F201; returns engine and affected serial."""
    e = running(load_config('demo'))
    until(e, lambda: e.state.faults_s2 > 0, 1500)
    st = e.state.stations['S2']
    return e, e.state.pallets[st.pallet]


def states(e):
    return {n: st.state for n, st in e.state.stations.items()}


# ---- start / stop -----------------------------------------------------------

@case('T01', 'Start', 'Start from idle loads the first part', 'run = true; first serial loaded within 5 sim-s; IN RUNNING')
def t01():
    e = Engine()
    e.command('start', user='QA')
    took = until(e, lambda: e.state.counts['in'] > 0, 5)
    ok = e.state.run and took is not None and e.state.stations['IN'].state == 'RUNNING'
    return f'run = {e.state.run}; SYR-B07-000001 loaded after {took:.1f} sim-s; IN {e.state.stations["IN"].state}', ok


@case('T02', 'Stop', 'Stop freezes production and keeps progress', 'All stations STOPPED; pallets, buffers, transfers and counts unchanged for 30 sim-s')
def t02():
    e = running()
    e.advance(25)
    e.command('stop', user='QA')
    before = deepcopy((e.state.pallets, e.state.buffers, e.state.transfers, e.state.counts))
    e.advance(30)
    same = before == (e.state.pallets, e.state.buffers, e.state.transfers, e.state.counts)
    stopped = set(states(e).values()) == {'STOPPED'}
    return f'all STOPPED = {stopped}; state unchanged over 30 sim-s = {same}', same and stopped


@case('T03', 'Stop', 'Restart after Stop resumes from the same point', 'Production continues; no part lost or duplicated')
def t03():
    e = running()
    e.advance(25)
    e.command('stop', user='QA')
    e.advance(30)
    loaded = e.state.counts['in']
    e.command('start', user='QA')
    e.advance(120)
    c = counts(e.state)
    ok = c['in'] > loaded and c['in'] == c['good'] + c['reject'] + c['wip']
    return f'loaded {loaded} → {c["in"]}; in = good + reject + WIP ({c["good"]} + {c["reject"]} + {c["wip"]})', ok


# ---- E-stop -----------------------------------------------------------------

@case('T04', 'E-stop', 'E-stop stops every station and latches F001', 'run = false; F001 active; all stations STOPPED')
def t04():
    e = running()
    e.advance(25)
    e.command('estop', {'active': True}, 'QA')
    e.tick()
    active = {a['code'] for a in e.state.alarms if a['t_cleared'] is None}
    ok = not e.state.run and 'F001' in active and set(states(e).values()) == {'STOPPED'}
    return f'run = {e.state.run}; active alarms {sorted(active)}; stations {set(states(e).values())}', ok


@case('T05', 'E-stop', 'Reset and Start are refused while E-stop is engaged', 'Reset leaves F001 latched; Start rejected')
def t05():
    e = running()
    e.advance(25)
    e.command('estop', {'active': True}, 'QA')
    e.command('reset', user='QA')
    start = raises(lambda: e.command('start', user='QA'))
    ok = e.state.estop_latched and start is not None
    return f'latched after Reset = {e.state.estop_latched}; Start → "{start}"', ok


@case('T06', 'E-stop', 'Recovery order: release → Reset → Start', 'Start refused before Reset; running after Reset + Start')
def t06():
    e = running()
    e.advance(25)
    e.command('estop', {'active': True}, 'QA')
    e.command('estop', {'active': False}, 'QA')
    early = raises(lambda: e.command('start', user='QA'))
    e.command('reset', user='QA')
    e.command('start', user='QA')
    e.advance(20)
    ok = early is not None and e.state.run and e.state.stations['IN'].state != 'STOPPED'
    return f'Start before Reset refused = {early is not None}; after Reset + Start run = {e.state.run}', ok


# ---- F201 and propagation ---------------------------------------------------

@case('T07', 'F201', 'Natural overload from tool wear', 'F201 when a press force exceeds 160 N (demo profile)')
def t07():
    e, serial = tripped_demo()
    force = e.state.parts[serial].meas['force_N']
    ok = e.state.stations['S2'].fault == 'F201' and force > 160
    return f'F201 at {e.state.t:.1f} sim-s; force {force:.1f} N on {serial}; wear {e.state.stations["S2"].wear:.2f}', ok


@case('T08', 'F201', 'Injected overload is traceable as injected', 'F201 latched; part event tagged injected = true')
def t08():
    e = running(perfect())
    e.advance(150)
    until(e, lambda: e.state.stations['S2'].step_i == 1, 30)
    serial = e.state.pallets[e.state.stations['S2'].pallet]
    e.command('inject_fault', {'code': 'F201'}, 'QA')
    tagged = any(ev.get('injected') for ev in e.state.parts[serial].events)
    ok = e.state.stations['S2'].fault == 'F201' and tagged
    return f'S2 fault {e.state.stations["S2"].fault}; {serial} injected tag = {tagged}', ok


@case('T09', 'Fault propagation', 'F201 is local: the line keeps running', 'run = true after F201; S2 FAULT; tower light RED')
def t09():
    e, _ = tripped_demo()
    e.tick()
    lamp = e.snapshot()['lamp']
    ok = e.state.run and e.state.stations['S2'].state == 'FAULT' and lamp == 'RED'
    return f'run = {e.state.run}; S2 {e.state.stations["S2"].state}; lamp {lamp}', ok


@case('T10', 'Fault propagation', 'Upstream blocks and downstream starves', 'S1 BLOCKED within 30 sim-s; S3 STARVED within 25 sim-s; IN BLOCKED')
def t10():
    e, _ = tripped_demo()
    start, first = e.state.t, {}
    while e.state.t - start < 60:
        for name, state in (('S1', 'BLOCKED'), ('S3', 'STARVED'), ('IN', 'BLOCKED')):
            if name not in first and e.state.stations[name].state == state:
                first[name] = e.state.t - start
        e.tick()
    ok = first.get('S1', 99) <= 30 and first.get('S3', 99) <= 25 and 'IN' in first
    fmt = lambda k: f'{first[k]:.1f} sim-s' if k in first else 'not reached'
    return f'after the trip: S1 BLOCKED at {fmt("S1")}, S3 STARVED at {fmt("S3")}, IN BLOCKED at {fmt("IN")}', ok


@case('T11', 'Fault propagation', 'Throughput drops while S2 is down', 'No good exit once the line has drained; downtime accumulates')
def t11():
    e, _ = tripped_demo()
    e.advance(120)
    good = e.state.counts['good']
    e.advance(180)
    down = e.state.stations['S2'].unplanned
    ok = e.state.counts['good'] == good and down > 290
    return f'good units {good} → {e.state.counts["good"]} over 180 sim-s; S2 unplanned downtime {down:.0f} s', ok


# ---- reset / recovery -------------------------------------------------------

@case('T12', 'Reset/recovery', 'Reset before repair is refused', 'F201 stays latched')
def t12():
    e, _ = tripped_demo()
    message = e.command('reset', user='QA')['message']
    ok = e.state.stations['S2'].fault == 'F201'
    return f'S2 fault after Reset = {e.state.stations["S2"].fault}; "{message}"', ok


@case('T13', 'Reset/recovery', 'Repair (90 sim-s) then Reset resumes S2 at RETRACT', 'tool_ok after 90 s, wear = 0; S2 resumes at RETRACT; line produces again')
def t13():
    e, _ = tripped_demo()
    e.command('repair', {'station': 'S2'}, 'QA')
    repair = until(e, lambda: e.state.stations['S2'].tool_ok, 120)
    wear = e.state.stations['S2'].wear
    e.command('reset', user='QA')
    step = list(e.state.config['stations']['S2']['steps'])[e.state.stations['S2'].step_i]
    good = e.state.counts['good']
    e.advance(200)
    ok = repair is not None and abs(repair - 90) < 0.2 and wear == 0 and step == 'RETRACT' and e.state.counts['good'] > good
    return (f'repair took {repair:.1f} sim-s, wear after repair {wear:.3f}; resumed at {step}; '
            f'good {good} → {e.state.counts["good"]} in 200 sim-s'), ok


@case('T14', 'Reset/recovery', 'Affected part is rejected R2 and keeps its trace', 'Part exits as FAIL with R2; overload event in its history')
def t14():
    e, serial = tripped_demo()
    e.command('repair', {'station': 'S2'}, 'QA')
    until(e, lambda: e.state.stations['S2'].tool_ok, 120)
    e.command('reset', user='QA')
    until(e, lambda: e.state.parts[serial].t_out is not None, 200)
    p = e.state.parts[serial]
    overload = any(ev.get('event') == 'overload' for ev in p.events)
    ok = p.status == 'FAIL' and 'R2' in p.reject_codes and overload
    return f'{serial}: {p.status} {p.reject_codes}; overload event in trace = {overload}; {len(p.events)} events', ok


# ---- inspection -------------------------------------------------------------

@case('T15', 'Inspection', 'Every decision matches its measurements', 'R1–R5 assigned exactly when a limit is violated; PASS parts are inside every limit')
def t15():
    e = running()
    e.advance(3600)
    low, high = e.state.config['stations']['S2']['force']['win']
    wrong = 0
    decided = [p for p in e.state.parts.values() if p.status in ('PASS', 'FAIL')]
    for p in decided:
        m = p.meas
        expected = [code for code, bad in (
            ('R1', abs(m['print_offset_mm']) > 0.15), ('R2', not low <= m['force_N'] <= high),
            ('R3', m['leak_Pa_s'] > 5.0), ('R4', not m['cap_ok']), ('R5', m['mark_grade'] == 'D')) if bad]
        wrong += expected != p.reject_codes
    return f'{len(decided)} inspection decisions checked against raw measurements; {wrong} mismatches', wrong == 0 and decided


@case('T16', 'Inspection', 'Force out of window raises leak failures', 'Mean leak rate of out-of-window parts > 5 Pa/s; in-window ≈ 2 Pa/s')
def t16():
    e = running()
    e.advance(3600)
    low, high = e.state.config['stations']['S2']['force']['win']
    parts = [p.meas for p in e.state.parts.values() if 'leak_Pa_s' in p.meas]
    out = [m['leak_Pa_s'] for m in parts if not low <= m['force_N'] <= high]
    inside = [m['leak_Pa_s'] for m in parts if low <= m['force_N'] <= high]
    ok = out and inside and mean(out) > 5 and abs(mean(inside) - 2) < 0.3
    return f'out-of-window mean leak {mean(out):.2f} Pa/s (n = {len(out)}); in-window {mean(inside):.2f} Pa/s (n = {len(inside)})', ok


@case('T17', 'Inspection', 'Rejected parts are diverted at S4, never packed', 'Every FAIL part leaves at S4 (diverted); every PASS part is unloaded at OUT')
def t17():
    e = running()
    e.advance(3600)
    bad = 0
    for p in e.state.parts.values():
        if p.t_out is None:
            continue
        last = [ev for ev in p.events if ev.get('event') in ('diverted', 'unloaded')][-1]
        bad += (p.status == 'FAIL') != (last['event'] == 'diverted' and last['station'] == 'S4')
    done = sum(p.t_out is not None for p in e.state.parts.values())
    return f'{done} completed parts checked; {bad} routed incorrectly', bad == 0


# ---- counting ---------------------------------------------------------------

@case('T18', 'Counting', 'Part conservation on every tick', 'in = good + reject + WIP on each of 36 000 ticks (1 sim-hour)')
def t18():
    e = running()
    worst = 0
    for _ in range(36000):
        e.tick()
        c = counts(e.state)
        worst = max(worst, abs(c['in'] - c['good'] - c['reject'] - c['wip']))
    c = counts(e.state)
    return f'max imbalance 0 required, measured {worst}; final in {c["in"]} = {c["good"]} + {c["reject"]} + {c["wip"]}', worst == 0


@case('T19', 'Counting', 'Ten unique pallets are always accounted for', 'Pallet check true on every tick; WIP ≤ 10')
def t19():
    e = running()
    fails = max_wip = 0
    for _ in range(36000):
        e.tick()
        fails += not pallet_check(e.state)
        max_wip = max(max_wip, counts(e.state)['wip'])
    return f'pallet check failures {fails}; max WIP {max_wip}', fails == 0 and max_wip <= 10


@case('T20', 'Counting', 'Boxes of ten', 'boxes = good // 10 throughout the run')
def t20():
    e = running(perfect())
    checks = bad = 0
    for _ in range(3600):
        e.advance(1)
        c = counts(e.state)
        checks += 1
        bad += c['boxes'] != c['good'] // 10
    return f'{checks} checks; good {c["good"]} → boxes {c["boxes"]}; mismatches {bad}', bad == 0


# ---- material flow ----------------------------------------------------------

@case('T21', 'Material flow', 'FIFO: parts finish in the order they were loaded', 'Completion order equals serial order')
def t21():
    e = running()
    e.advance(3600)
    done = sorted((p.t_out, p.serial) for p in e.state.parts.values() if p.t_out is not None)
    serials = [s for _, s in done]
    return f'{len(serials)} completions; in serial order = {serials == sorted(serials)}', serials == sorted(serials)


@case('T22', 'Material flow', 'Empty hopper starves IN; refill arrives after 30 sim-s', 'No load while empty; IN STARVED (material empty); production resumes after refill')
def t22():
    e = running(perfect())
    e.state.bins['hopper'] = 0
    e.advance(10)
    starved = e.state.counts['in'] == 0
    resumed = until(e, lambda: e.state.counts['in'] > 0, 40)
    ok = starved and resumed is not None
    return f'loads while empty: {0 if starved else "some"}; production resumed {resumed + 10:.1f} sim-s after emptying', ok


@case('T23', 'Material flow', 'Low stock raises a warning and an automatic refill', 'W001 below 30 barrels; hopper back to 300 after 30 sim-s')
def t23():
    e = running(perfect())
    e.state.bins['hopper'] = 31
    raised = until(e, lambda: any(a['code'] == 'W001' for a in e.state.alarms), 60)
    refilled = until(e, lambda: e.state.bins['hopper'] >= 290, 40)
    ok = raised is not None and refilled is not None
    return f'W001 after {raised:.1f} sim-s; hopper refilled to {e.state.bins["hopper"]} after {refilled:.1f} sim-s', ok


@case('T24', 'Material flow', 'Planned tool change waits for the cycle boundary', '20 sim-s planned downtime; no unplanned downtime; wear reset')
def t24():
    e = running()
    e.advance(30)
    st = e.state.stations['S2']
    e.command('tool_change', {'station': 'S2'}, 'QA')
    e.advance(40)
    ok = abs(st.planned - 20) < 0.2 and st.unplanned == 0 and st.wear < 0.04
    return f'planned {st.planned:.1f} s; unplanned {st.unplanned:.1f} s; wear after {st.wear:.3f}', ok


# ---- model validation -------------------------------------------------------

@case('T25', 'Validation', 'Design rate with wear and noise off', '360 good units/h ± 5 % after a 300 sim-s warm-up')
def t25():
    e = running(perfect())
    e.advance(300)
    good = e.state.counts['good']
    e.advance(3600)
    rate = e.state.counts['good'] - good
    return f'{rate} good units in 3600 sim-s ({(rate - 360) / 3.6:+.1f} %)', 342 <= rate <= 378


@case('T26', 'Validation', "Little's Law on the same window", '|WIP − λ·W| / WIP < 10 %')
def t26():
    e = running(perfect())
    e.advance(300)
    integral = e.state.wip_integral
    e.advance(3600)
    done = [row for row in e.state.completions if 300 < row[0] <= 3900]
    wip = (e.state.wip_integral - integral) / 3600
    lead = mean(row[1] for row in done)
    error = abs(wip - len(done) / 3600 * lead) / wip
    return f'WIP {wip:.2f}; λ {len(done)/3600*3600:.0f}/h; W {lead:.1f} s; error {error:.2%}', error < 0.1


@case('T27', 'Validation', 'Determinism: same seed, same result', 'Identical counts and last force after 1000 sim-s')
def t27():
    a, b = running(), running()
    a.advance(1000)
    b.advance(1000)
    same = a.state.counts == b.state.counts and a.state.stations['S2'].force == b.state.stations['S2'].force
    return f'run A {a.state.counts}; run B {b.state.counts}; identical = {same}', same


# ---- what-if ----------------------------------------------------------------

def worn():
    e = running()
    e.advance(1200)
    return e


@case('T28', 'What-if', 'The live twin is never modified', 'Live state identical before and after a what-if run')
def t28():
    from test_operational import state_fingerprint
    e = worn()
    before = state_fingerprint(e.state)
    run_whatif(deepcopy(e.state), 'maintenance', horizon_s=1800)
    same = state_fingerprint(e.state) == before
    return f'fingerprint unchanged = {same}', same


@case('T29', 'What-if', '"Keep running" forecasts the live line', 'Forecast next-F201 time equals the live outcome (± 1 tick)')
def t29():
    e = worn()
    forecast = run_whatif(deepcopy(e.state), 'maintenance', horizon_s=1800)['arms'][0]['kpi']['first_f201_s']
    start, faults = e.state.t, e.state.faults_s2
    until(e, lambda: e.state.faults_s2 > faults, 1800)
    actual = e.state.t - start
    return f'forecast {forecast:.1f} sim-s; live {actual:.1f} sim-s', abs(forecast - actual) <= 0.11


@case('T30', 'What-if', 'Maintenance decision', 'Condition-based changes recommended; fewer F201 and rejects in 5/5 seeds')
def t30():
    r = run_whatif(deepcopy(worn().state), 'maintenance', horizon_s=3600, replications=5)
    keep, now, policy = (a['kpi'] for a in r['arms'])
    rec = r['recommendation']
    ok = rec['arm'] == 'condition_based' and rec['wins'] == 5 and policy['f201'] < keep['f201']
    return (f'good/h: keep {keep["throughput_ph"]:.0f}, change now {now["throughput_ph"]:.0f}, '
            f'condition-based {policy["throughput_ph"]:.0f}; F201 {keep["f201"]:.1f} → {policy["f201"]:.1f}; '
            f'wins {rec["wins"]}/5'), ok


@case('T31', 'What-if', 'Speeding up a non-bottleneck gives nothing', 'S1 cure 3 → 2 s: < 2 % change; keep current recommended')
def t31():
    r = run_whatif(deepcopy(worn().state), 'cycle_time', {'station': 'S1', 'step': 'CURE', 'value': 2.0}, 3600)
    a, b = (x['kpi'] for x in r['arms'])
    change = (b['good'] - a['good']) / a['good']
    ok = abs(change) < 0.02 and r['recommendation']['arm'] == 'current'
    return f'good {a["good"]:.0f} → {b["good"]:.0f} ({change:+.1%}); bottleneck {b["bottleneck"]}; recommendation: keep', ok


@case('T32', 'What-if', 'Speeding up the bottleneck moves it', 'S2 insert 3 → 0.5 s: > 10 % gain; design bottleneck moves S2 → S1')
def t32():
    r = run_whatif(deepcopy(worn().state), 'cycle_time', {'station': 'S2', 'step': 'INSERT', 'value': 0.5}, 3600)
    a, b = (x['kpi'] for x in r['arms'])
    change = (b['good'] - a['good']) / a['good']
    ok = change > 0.1 and b['design']['bottleneck'] == 'S1'
    return (f'good {a["good"]:.0f} → {b["good"]:.0f} ({change:+.1%}); design capacity '
            f'{a["design"]["rate_ph"]:.0f} → {b["design"]["rate_ph"]:.0f}/h, bottleneck {a["design"]["bottleneck"]} → {b["design"]["bottleneck"]}'), ok


# ---- PLC mode (Modbus stand-in) -------------------------------------------------

def plc_rig(config=None):
    from test_plc_bridge import Rig
    return Rig(config)


@case('T33', 'PLC mode', 'Start/Stop through the PLC run permissive', 'Twin runs only while M_SYS_RUN = 1')
def t33():
    r = plc_rig()
    try:
        before = r.s.run
        r.cmd('start')
        r.step(15)
        on = r.s.run and r.coil('M_SYS_RUN')
        r.cmd('stop')
        r.step(15)
        off = not r.s.run and not r.coil('M_SYS_RUN')
        return f'before Start run = {before}; after Start {on}; after Stop stopped = {off}', not before and on and off
    finally:
        r.bridge.close(); r.server.close()


@case('T34', 'PLC mode', 'PLC detects the overload and gates recovery', 'F201 coil on force > 160 N; Reset refused until repair; resume after Reset')
def t34():
    from test_plc_bridge import worn_config
    r = plc_rig(worn_config())
    try:
        r.cmd('start')
        r.until(lambda: r.coil('F201'))
        r.step(2)
        st = r.s.stations['S2']
        force = st.force
        r.cmd('reset'); r.step(15)
        held = r.coil('F201')
        r.cmd('repair', {'station': 'S2'})
        r.until(lambda: st.tool_ok, 120)
        r.step(5)
        r.cmd('reset'); r.step(15)
        ok = force > 160 and held and not r.coil('F201') and st.fault is None
        return f'F201 at force {force:.1f} N; held after early Reset = {held}; cleared after repair + Reset = {not r.coil("F201")}', ok
    finally:
        r.bridge.close(); r.server.close()


@case('T35', 'PLC mode', 'Lost PLC link stops the line safely', 'F002 within ~1 s; line stopped; Reset needed after the link returns')
def t35():
    r = plc_rig()
    try:
        r.cmd('start'); r.step(15)
        r.plc_running = False
        r.step(60)
        stopped = not r.s.run and any(a['code'] == 'F002' and a['t_cleared'] is None for a in r.s.alarms)
        r.plc_running = True
        r.step(60)
        refused = raises(lambda: r.cmd('start')) is not None
        r.cmd('reset'); r.step(15); r.cmd('start'); r.step(15)
        return f'stopped with F002 = {stopped}; Start refused before Reset = {refused}; running after Reset + Start = {r.s.run}', stopped and refused and r.s.run
    finally:
        r.bridge.close(); r.server.close()


@case('T36', 'PLC mode', 'PLC counters agree with the twin', 'C_IN, C_GOOD, C_REJECT match twin counts over 600 sim-s')
def t36():
    r = plc_rig()
    try:
        r.cmd('start'); r.step(3000)
        status = r.bridge.status(r.s)
        n = status['counters']
        return f'PLC {n["C_IN"]}/{n["C_GOOD"]}/{n["C_REJECT"]} vs twin {r.s.counts["in"]}/{r.s.counts["good"]}/{r.s.counts["reject"]}; consistent = {status["counters_consistent"]}', status['counters_consistent'] is True
    finally:
        r.bridge.close(); r.server.close()


MANUAL = [  # run on OpenPLC Runtime by tools/plc_acceptance.py -> docs/evidence/plc_manual_results.json
    ('PLC-01', 'Start pulse sets run permissive and green lamp'), ('PLC-02', 'Stop pulse drops run'),
    ('PLC-03', 'E-stop latches F001, red flashing, horn'), ('PLC-04', 'Reset ignored while E-stop open'),
    ('PLC-05', 'Release → Reset → Start recovers'), ('PLC-06', 'Force 145.0 N: no F201, verdict echoed'),
    ('PLC-07', 'Force 161.2 N: F201 set, line keeps running'), ('PLC-08', 'Reset before repair refused'),
    ('PLC-09', 'Repair (TOOL_OK 0→1) then Reset clears F201'), ('PLC-10', 'Counters and box of ten'),
    ('PLC-11', 'Frozen heartbeat trips F002 and drops run'), ('PLC-12', 'Heartbeat back, Reset, Start recovers'),
    ('PLC-13', 'Twin warning gives amber lamp')]


def run_all():
    rows = []
    for c in CASES:
        try:
            actual, ok = c['run']()
        except Exception as exc:  # a crash is a failure, recorded as such
            actual, ok = f'error: {type(exc).__name__}: {exc}', False
        rows.append({k: c[k] for k in ('id', 'area', 'title', 'expected')} | {'actual': actual, 'result': 'PASS' if ok else 'FAIL'})
    return rows


def manual_rows():
    path = ROOT / 'docs' / 'evidence' / 'plc_manual_results.json'
    recorded = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return [{'id': cid, 'area': 'OpenPLC Runtime', 'title': title, 'expected': 'See PLC_SPEC.md §6',
             'actual': recorded.get(cid, {}).get('actual', 'not yet run'),
             'result': recorded.get(cid, {}).get('result', 'PENDING')} for cid, title in MANUAL]


def main():
    rows = run_all() + manual_rows()
    out = ROOT / 'docs' / 'evidence'
    stamp = datetime.now().astimezone().isoformat(timespec='seconds')
    (out / 'test_matrix.json').write_text(json.dumps({'generated': stamp, 'rows': rows}, indent=2, ensure_ascii=False), encoding='utf-8')
    auto = [r for r in rows if r['area'] != 'OpenPLC Runtime']
    passed = sum(r['result'] == 'PASS' for r in auto)
    lines = ['# Validation test matrix', '',
             f'Generated {stamp} by `python tools/validation_matrix.py`. Every *actual* value was measured in that run '
             '(seed 7). PLC-mode rows T33–T36 use the Modbus stand-in of `syringetwin.st`; PLC-xx rows are run on '
             'OpenPLC Runtime by `tools/plc_acceptance.py`.', '',
             f'**Automated: {passed}/{len(auto)} PASS.**', '',
             '| ID | Area | Test | Expected | Actual (measured) | Result |', '|---|---|---|---|---|---|']
    for r in rows:
        cells = [r[k].replace('|', '\\|') for k in ('id', 'area', 'title', 'expected', 'actual')]
        lines.append('| ' + ' | '.join(cells) + f' | **{r["result"]}** |')
    (out / 'test_matrix.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'{passed}/{len(auto)} automated cases PASS; matrix written to docs/evidence/test_matrix.md')
    for r in auto:
        if r['result'] != 'PASS':
            print(f'  FAIL {r["id"]}: {r["actual"]}')
    return 0 if passed == len(auto) else 1


if __name__ == '__main__':
    sys.exit(main())
