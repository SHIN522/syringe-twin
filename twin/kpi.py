"""Measured KPIs; null denominators remain null (brief section 9)."""
from statistics import mean
from .control import prediction


def ratio(a, b):
    return a / b if b > 0 else None


def pallet_check(s):
    locations = list(s.empty)
    locations += [st.pallet for st in s.stations.values() if st.pallet is not None]
    locations += [p for values in s.buffers.values() for p in values]
    locations += [tr.pallet for tr in s.transfers]
    return sorted(locations) == sorted(s.pallets) and len(set(locations)) == len(locations)


def counts(s):
    result = dict(s.counts)
    result['wip'] = sum(p.t_out is None for p in s.parts.values())
    result['boxes'] = result['good'] // 10
    return result


def calculate(s):
    st = s.stations['S2']
    c = counts(s)
    available = s.planned_time - st.unplanned - st.planned
    a = ratio(available, s.planned_time)
    p = ratio(s.config['design_cycle_s'] * st.cycles, available)
    q = ratio(s.passes, s.decisions)
    recent = [t for t in s.good_exits if t > s.t - 600]
    tail = s.good_exits[-21:]
    intervals = [b-a for a,b in zip(tail, tail[1:])]
    # Little's Law is certified offline in the warm-up-aligned evidence test.
    result = {'t': s.t, 'win_s': 600, 'th_ph': len(recent)*6,
              'line_ct_s': mean(intervals) if intervals else None,
              'lead_s': mean(x[1] for x in s.completions) if s.completions else None,
              'A': a, 'P': p, 'Q': q, 'oee': a*p*q if None not in (a,p,q) else None,
              'yield': q, 'wip_avg': ratio(s.wip_integral, s.t),
              'down_s': {'S2': {'unplanned': st.unplanned, 'planned': st.planned}},
              'mtbf_s': ratio(available, s.faults_s2),
              'mttr_s': ratio(st.unplanned, s.faults_s2), 'pareto': dict(s.pareto),
              's2': {'health': max(0,1-st.wear), 'cycles_to_fault': prediction(s)},
              'check': {'conservation': c['in']==c['good']+c['reject']+c['wip'],
                        'little_err': None, 'pallet_conservation': pallet_check(s)}}
    return result
