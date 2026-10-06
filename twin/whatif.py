"""What-if decision support (brief U4, DECISIONS D8 and D11).

Copy the live twin, change one thing, run every arm forward headless from the
same state with the same random numbers, then compare KPIs and recommend.
The live state is only read (deep-copied); it is never modified.
"""
from copy import deepcopy
from math import ceil
from statistics import mean
from time import perf_counter
import numpy as np
from .engine import Engine
from .events import active_alarms, clear_alarm
from .kpi import counts
from .control import prediction
from .model import STATIONS

OPERATOR = 'What-if operator'
HORIZONS = (1800, 3600, 7200)
ACTIVE = ('RUNNING', 'FAULT', 'MAINT')
MIN_GAIN = 0.02  # a change must add at least 2 % good units to be recommended


# ---- scenario definitions -------------------------------------------------

def scenarios(config):
    """Options the dashboard offers; durations come from the live config."""
    steps = {name: dict(config['stations'][name]['steps']) for name in ('S1', 'S2', 'S3', 'S4')}
    return {
        'maintenance': {
            'title': 'Worn tool: keep running or maintain?',
            'question': 'S2 tool wear is rising. Is it better to keep producing, change the tool now, '
                        'or change it whenever the condition monitor raises W202?',
            'params': {}},
        'cycle_time': {
            'title': 'Faster step: real gain or moved bottleneck?',
            'question': 'Shorten one process step and see whether throughput rises '
                        'or the bottleneck simply moves.',
            'params': {'steps': steps},
            'presets': [
                {'label': 'S1 cure 3.0 → 2.0 s', 'station': 'S1', 'step': 'CURE', 'value': 2.0},
                {'label': 'S2 insert 3.0 → 2.0 s', 'station': 'S2', 'step': 'INSERT', 'value': 2.0},
                {'label': 'S2 insert 3.0 → 0.5 s', 'station': 'S2', 'step': 'INSERT', 'value': 0.5}]},
        'horizons_s': list(HORIZONS),
        'replications': [1, 5]}


def _set_policy(on):
    def apply(e):
        e.state.config['policy']['predictive_tool_change'] = on
    return apply


def _tool_change_now(e):
    _set_policy(False)(e)
    st = e.state.stations['S2']
    if not st.fault and not st.maintenance:
        e.command('tool_change', {'station': 'S2'}, OPERATOR)


def _arms(scenario, params, config):
    if scenario == 'maintenance':
        return [
            {'id': 'continue', 'label': 'Keep running',
             'description': 'No planned maintenance; repair S2 after each F201.',
             'apply': _set_policy(False)},
            {'id': 'tool_change_now', 'label': 'Change tool now',
             'description': 'One planned 20 s tool change at the next S2 cycle boundary, then run to failure.',
             'apply': _tool_change_now},
            {'id': 'condition_based', 'label': 'Condition-based changes',
             'description': 'Change the tool whenever W202 is raised (force > 135 N or < 60 cycles to overload).',
             'apply': _set_policy(True)}]
    if scenario == 'cycle_time':
        station, step, value = params.get('station'), params.get('step'), params.get('value')
        if station not in ('S1', 'S2', 'S3', 'S4') or step not in config['stations'][station]['steps']:
            raise ValueError('Choose a process step of S1, S2, S3 or S4.')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.1 <= value <= 30:
            raise ValueError('Step duration must be between 0.1 and 30 seconds.')
        current = config['stations'][station]['steps'][step]

        def modify(e):
            _set_policy(True)(e)
            e.state.config['stations'][station]['steps'][step] = float(value)
        return [
            {'id': 'current', 'label': f'{station} {step.lower()} {current:g} s (current)',
             'description': 'Current process timing.', 'apply': _set_policy(True)},
            {'id': 'modified', 'label': f'{station} {step.lower()} {value:g} s',
             'description': f'{station} {step} changed from {current:g} s to {value:g} s.', 'apply': modify}]
    raise ValueError('Unknown what-if scenario: ' + str(scenario))


# ---- running one arm --------------------------------------------------------

def design_capacity(config):
    """Static capacity: each station's cycle = its steps + one pallet transfer."""
    cycles = {name: sum(config['stations'][name]['steps'].values()) + config['transfer_s']
              for name in ('IN', 'S1', 'S2', 'S3', 'S4')}
    bottleneck = max(cycles, key=cycles.get)
    return {'cycles_s': cycles, 'bottleneck': bottleneck, 'rate_ph': 3600 / cycles[bottleneck]}


def _prepare(state, replication):
    """Fork assumptions: the line is producing, and replications > 0 draw fresh random numbers."""
    s = deepcopy(state)
    s.estop_active = s.estop_latched = False
    clear_alarm(s, 'F001')
    s.run = True
    if replication:
        s.rng = {name: np.random.default_rng([s.config['seed'], replication, i])
                 for i, name in enumerate(STATIONS)}
    return s


def _auto_operator(e):
    """Identical in every arm (D8): repair S2 at once, reset when the repair completes."""
    st = e.state.stations['S2']
    if st.fault and not st.maintenance and not st.tool_ok:
        e.command('repair', {'station': 'S2'}, OPERATOR)
    elif st.fault and st.tool_ok:
        e.command('reset', {}, OPERATOR)


def _ratio(a, b):
    return a / b if b > 0 else None


def run_arm(state, apply, horizon_s):
    e = Engine(state=state)
    s = e.state
    apply(e)
    st2 = s.stations['S2']
    start = {'t': s.t, 'counts': counts(s), 'planned_time': s.planned_time, 'faults': s.faults_s2,
             'unplanned': st2.unplanned, 'planned': st2.planned, 'cycles': st2.cycles,
             'passes': s.passes, 'decisions': s.decisions, 'pareto': dict(s.pareto),
             'completions': len(s.completions)}
    shares = {name: dict.fromkeys(('RUNNING', 'BLOCKED', 'STARVED', 'FAULT', 'MAINT', 'STOPPED'), 0)
              for name in STATIONS}
    first_fault = None
    ticks = round(horizon_s / s.config['dt'])
    for _ in range(ticks):
        _auto_operator(e)
        e.tick()
        for name, st in s.stations.items():
            shares[name][st.state] += 1
        if first_fault is None and s.faults_s2 > start['faults']:
            first_fault = s.t - start['t']
    end = counts(s)
    good = end['good'] - start['counts']['good']
    planned_time = s.planned_time - start['planned_time']
    unplanned = st2.unplanned - start['unplanned']
    planned = st2.planned - start['planned']
    available = planned_time - unplanned - planned
    ideal = sum(s.config['stations']['S2']['steps'].values()) + s.config['transfer_s']
    a = _ratio(available, planned_time)
    p = _ratio(ideal * (st2.cycles - start['cycles']), available)
    q = _ratio(s.passes - start['passes'], s.decisions - start['decisions'])
    utilisation = {name: {k: v / ticks for k, v in row.items() if v} for name, row in shares.items()}
    active = {name: sum(u.get(k, 0) for k in ACTIVE) for name, u in utilisation.items() if name != 'OUT'}
    window = s.completions[start['completions']:]
    return {
        'good': good, 'reject': end['reject'] - start['counts']['reject'],
        'loaded': end['in'] - start['counts']['in'],
        'throughput_ph': good * 3600 / horizon_s,
        'A': a, 'P': p, 'Q': q, 'oee': a * p * q if None not in (a, p, q) else None,
        'f201': s.faults_s2 - start['faults'], 'first_f201_s': first_fault,
        'unplanned_s': unplanned, 'planned_s': planned,
        'lead_s': mean(row[1] for row in window) if window else None,
        'pareto': {code: n - start['pareto'].get(code, 0) for code, n in s.pareto.items()
                   if n - start['pareto'].get(code, 0)},
        'utilisation': utilisation, 'active_share': active,
        'bottleneck': max(active, key=active.get),
        'design': design_capacity(s.config),
        'end_wear': st2.wear}


# ---- comparison and recommendation -----------------------------------------

COMPARE = [  # key, label, unit, better
    ('good', 'Good units', 'units', 'higher'),
    ('throughput_ph', 'Good throughput', 'units/h', 'higher'),
    ('reject', 'Rejected units', 'units', 'lower'),
    ('Q', 'First-pass quality', '%', 'higher'),
    ('oee', 'OEE (S2)', '%', 'higher'),
    ('A', 'Availability', '%', 'higher'),
    ('f201', 'F201 overloads', 'trips', 'lower'),
    ('unplanned_s', 'Unplanned downtime', 's', 'lower'),
    ('planned_s', 'Planned downtime', 's', 'lower'),
    ('lead_s', 'Mean lead time', 's', 'lower')]


def _average(results):
    keys = [k for k, *_ in COMPARE] + ['P', 'loaded', 'end_wear']
    avg = {}
    for k in keys:
        values = [r[k] for r in results if r[k] is not None]
        avg[k] = mean(values) if values else None
    firsts = [r['first_f201_s'] for r in results if r['first_f201_s'] is not None]
    avg['first_f201_s'] = mean(firsts) if len(firsts) == len(results) else None
    avg['good_range'] = [min(r['good'] for r in results), max(r['good'] for r in results)]
    first = results[0]
    for k in ('pareto', 'utilisation', 'active_share', 'bottleneck', 'design'):
        avg[k] = first[k]  # replication 0 is the twin's own continuation
    return avg


def _recommend(scenario, arms, replications):
    base = arms[0]
    best = max(arms, key=lambda arm: arm['kpi']['good'])
    wins = sum(b > a for a, b in zip(base['runs_good'], best['runs_good']))
    gain = _ratio(best['kpi']['good'] - base['kpi']['good'], base['kpi']['good']) or 0
    needed = ceil(0.8 * replications)
    reasons = []
    if best is base or gain < MIN_GAIN or wins < needed:
        action = base
        headline = f'Keep current: no option adds {MIN_GAIN:.0%} or more good output.'
    else:
        action = best
        per_hour = best['kpi']['throughput_ph'] - base['kpi']['throughput_ph']
        versus = '"keep running"' if scenario == 'maintenance' else 'the current timing'
        headline = f'{best["label"]}: {per_hour:+.0f} good units/h ({gain:+.0%}) compared with {versus}.'
    b, k = base['kpi'], action['kpi']
    if scenario == 'maintenance':
        if b['first_f201_s'] is not None:
            reasons.append(f'If nothing changes, the next F201 overload comes in about {b["first_f201_s"]/60:.1f} sim-minutes.')
        if action is not base:
            reasons.append(f'F201 overloads {b["f201"]:.1f} → {k["f201"]:.1f}; unplanned downtime '
                           f'{b["unplanned_s"]:.0f} → {k["unplanned_s"]:.0f} s; planned downtime '
                           f'{b["planned_s"]:.0f} → {k["planned_s"]:.0f} s.')
            reasons.append(f'Rejects {b["reject"]:.0f} → {k["reject"]:.0f}: lower tool wear keeps press force inside 105–140 N.')
    else:
        mod = arms[1]['kpi']
        if b['design']['bottleneck'] == mod['design']['bottleneck']:
            reasons.append(f'Design bottleneck stays {mod["design"]["bottleneck"]} '
                           f'({b["design"]["rate_ph"]:.0f} → {mod["design"]["rate_ph"]:.0f} units/h capacity).')
        else:
            reasons.append(f'Design bottleneck moves {b["design"]["bottleneck"]} → {mod["design"]["bottleneck"]}; '
                           f'capacity {b["design"]["rate_ph"]:.0f} → {mod["design"]["rate_ph"]:.0f} units/h.')
        busy = mod['active_share']
        ranked = sorted(busy, key=busy.get, reverse=True)
        share = f'{busy[ranked[0]]:.0%} active vs {ranked[1]} {busy[ranked[1]]:.0%}'
        if b['bottleneck'] != mod['bottleneck']:
            reasons.append(f'Simulated bottleneck (busiest station incl. downtime) moves {b["bottleneck"]} → {mod["bottleneck"]} ({share}).')
        elif mod['design']['bottleneck'] != mod['bottleneck']:
            reasons.append(f'On paper the bottleneck moves to {mod["design"]["bottleneck"]}, but with downtime included '
                           f'{mod["bottleneck"]} is still the busiest station ({share}).')
        else:
            reasons.append(f'Simulated bottleneck stays {mod["bottleneck"]} ({share}).')
    if replications > 1:
        reasons.append(f'Best option produced more than the first option in {wins} of {replications} random-seed replications '
                       f'(range {best["kpi"]["good_range"][0]}–{best["kpi"]["good_range"][1]} good units).')
    return {'arm': action['id'], 'label': action['label'], 'headline': headline,
            'reasons': reasons, 'wins': wins, 'replications': replications, 'gain': gain}


def snapshot_of(state):
    st = state.stations['S2']
    return {'t': state.t, 'run': state.run, 'counts': counts(state), 'wear': st.wear,
            'health': max(0.0, 1 - st.wear), 'force': st.force, 'cycles_to_fault': prediction(state),
            's2_state': st.state, 'active_alarms': [a['code'] for a in active_alarms(state)]}


def run_whatif(state, scenario, params=None, horizon_s=3600, replications=1):
    """`state` must already be a private copy (the API copies it under the engine lock)."""
    params = params or {}
    if horizon_s not in HORIZONS:
        raise ValueError(f'Horizon must be one of {HORIZONS} sim-seconds.')
    if replications not in (1, 3, 5):
        raise ValueError('Replications must be 1, 3 or 5.')
    began = perf_counter()
    arms = _arms(scenario, params, state.config)
    out = []
    for arm in arms:
        runs = [run_arm(_prepare(state, r), arm['apply'], horizon_s) for r in range(replications)]
        out.append({'id': arm['id'], 'label': arm['label'], 'description': arm['description'],
                    'kpi': _average(runs), 'runs_good': [r['good'] for r in runs]})
    comparison = []
    for key, label, unit, better in COMPARE:
        values = [a['kpi'][key] for a in out]
        base = values[0]
        comparison.append({'key': key, 'label': label, 'unit': unit, 'better': better, 'values': values,
                           'deltas': [None if v is None or base is None else v - base for v in values]})
    return {
        'scenario': scenario, 'title': scenarios(state.config)[scenario]['title'],
        'horizon_s': horizon_s, 'replications': replications, 'fork': snapshot_of(state),
        'arms': out, 'comparison': comparison,
        'recommendation': _recommend(scenario, out, replications),
        'assumptions': [
            'Every option starts from the same copy of the live twin with the same random numbers.',
            'The copy is producing: an E-stop or operator stop in the live line is not carried into it.',
            'Automatic operator in every option: repair S2 immediately after F201, reset when the repair completes; bins refill automatically.',
            'Replication 1 continues the twin\'s own random sequence; further replications use fresh seeds.'] +
            (['Both options use condition-based tool changes, so tool wear does not distort the timing comparison.']
             if scenario == 'cycle_time' else []),
        'runtime_s': perf_counter() - began}
