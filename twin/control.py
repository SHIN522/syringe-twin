"""Sequence control and transfer interlocks (brief sections 4, 5 and 11).

Dashboard MVP: explicit SFC actions, not a certified PLC or full P1-P9 I/O scan.
"""
from .model import Part, Transfer, STATIONS
from .events import event, alarm, active_alarms, trip_s2
from .plant import serial_at

ROUTE = {'IN':'B1', 'S1':'B2', 'S2':'B3', 'S3':'B4', 'S4':'OUT'}
FEED = {'B1':'S1','B2':'S2','B3':'S3','B4':'S4'}


def reserved(s, dest):
    return sum(tr.destination == dest for tr in s.transfers)


def room(s, dest):
    if dest in s.buffers:
        return len(s.buffers[dest]) + reserved(s, dest) < s.config['buffers'][dest]
    return s.stations[dest].pallet is None and not reserved(s, dest)


def transfer(s, pid, source, dest):
    duration = s.config['return_s'] if dest == 'RETURN' else s.config['transfer_s']
    s.transfers.append(Transfer(pid, source, dest, duration, duration))
    event(s, 'part', source, s.pallets[pid], event='released', destination=dest)


def release(s, name, dest):
    st = s.stations[name]
    pid = st.pallet
    transfer(s, pid, name, dest)
    st.pallet, st.step_i, st.elapsed, st.done = None, -1, 0.0, False


def material_ok(s, name):
    required = {'IN':['hopper'],'S2':['plunger','stopper'],'S3':['cap']}.get(name, [])
    return all(s.bins[b] > 0 for b in required)


def begin(s, name):
    st = s.stations[name]
    st.step_i, st.elapsed, st.cycle_start = 0, 0.0, s.t
    if name == 'IN':
        s.counts['in'] += 1
        serial = f"SYR-B07-{s.counts['in']:06d}"
        s.pallets[st.pallet] = serial
        s.parts[serial] = Part(serial, s.t)
        s.bins['hopper'] -= 1
    elif name == 'S2':
        s.bins['plunger'] -= 1
        s.bins['stopper'] -= 1
    elif name == 'S3':
        s.bins['cap'] -= 1
    event(s, 'part', name, serial_at(s, name), event='cycle_start')


def inspect(s, serial):
    p, c = s.parts[serial], s.config['stations']['S4']
    low, high = s.config['stations']['S2']['force']['win']
    tests = [('R1', abs(p.meas.get('print_offset_mm', 1)) > 0.15),
             ('R2', not low <= p.meas.get('force_N', 0) <= high),
             ('R3', p.meas.get('leak_Pa_s', 100) > c['leak_limit']),
             ('R4', not p.meas.get('cap_ok', False)),
             ('R5', p.meas.get('mark_grade', 'D') == 'D')]
    p.reject_codes = [code for code, failed in tests if failed]
    p.status = 'FAIL' if p.reject_codes else 'PASS'
    s.decisions += 1
    s.passes += not p.reject_codes
    for code in p.reject_codes:
        s.pareto[code] = s.pareto.get(code, 0) + 1
    event(s, 'inspection', 'S4', serial, event='decision',
          status=p.status, reject_codes=p.reject_codes, meas=dict(p.meas))


def complete_part(s, name, good):
    serial = serial_at(s, name)
    p = s.parts[serial]
    p.t_out = s.t
    s.counts['good' if good else 'reject'] += 1
    s.completions.append((s.t, p.t_out - p.t_in, good))
    if good:
        s.good_exits.append(s.t)
        if s.counts['good'] % 10 == 0:
            event(s, 'box', name, serial, box=s.counts['good'] // 10)
    event(s, 'part', name, serial, event='unloaded' if good else 'diverted')
    s.pallets[s.stations[name].pallet] = None


def finished_step(s, name):
    st = s.stations[name]
    if not st.done or st.step_i >= len(s.config['stations'][name]['steps']):
        return
    steps = list(s.config['stations'][name]['steps'])
    step = steps[st.step_i]
    if name == 'S2' and step == 'PRESS':
        if st.force > s.config['stations']['S2']['force']['trip']:
            trip_s2(s)
            st.done = False
            return
    if name == 'S4' and step == 'DECIDE':
        inspect(s, serial_at(s, name))
    st.step_i += 1
    if st.step_i < len(steps):
        st.done = False
        return
    st.last_ct = s.t - st.cycle_start
    st.cycle_times.append(st.last_ct)
    st.cycles += 1
    if name == 'OUT':
        complete_part(s, name, True)
        release(s, name, 'RETURN')
    elif name == 'S4' and s.parts[serial_at(s, name)].status == 'FAIL':
        complete_part(s, name, False)
        release(s, name, 'RETURN')


def process_station(s, name):
    st = s.stations[name]
    if st.fault:
        st.state, st.reason = 'FAULT', st.fault
        return False
    if st.maintenance:
        st.state = 'MAINT' if st.maintenance == 'tool_change' else 'FAULT'
        st.reason = st.maintenance
        return False
    if st.pending_tool_change and st.step_i == -1:
        st.maintenance, st.remaining = 'tool_change', s.config['stations']['S2']['tool_change_s']
        st.state, st.reason = 'MAINT', 'tool_change'
        return False
    if st.pallet is None:
        st.state, st.reason = 'STARVED', 'waiting for pallet'
        return False
    if st.step_i == -1:
        if not material_ok(s, name):
            st.state, st.reason = 'STARVED', 'material empty'
            return False
        begin(s, name)
    finished_step(s, name)
    if st.fault:
        st.state, st.reason = 'FAULT', st.fault
        return False
    if st.pallet is None:
        st.state, st.reason = 'STARVED', 'waiting for pallet'
        return False
    if st.step_i >= len(s.config['stations'][name]['steps']):
        dest = ROUTE[name]
        if room(s, dest):
            release(s, name, dest)
            st.state, st.reason = 'STARVED', 'waiting for pallet'
        else:
            st.state, st.reason = 'BLOCKED', dest + ' full'
        return False
    st.state, st.reason = 'RUNNING', None
    return True


def scan(s):
    if not s.run:
        for st in s.stations.values():
            st.state, st.reason = 'STOPPED', 'E-stop' if s.estop_latched else 'operator stop'
        return []
    # Downstream first, avoiding a needless extra scan on release.
    enabled = [name for name in reversed(STATIONS) if process_station(s, name)]
    for buf, dest in FEED.items():
        if s.buffers[buf] and room(s, dest):
            transfer(s, s.buffers[buf].pop(0), buf, dest)
    if s.empty and room(s, 'IN') and s.bins['hopper'] > 0:
        s.stations['IN'].pallet = s.empty.pop(0)
    return enabled


def material_policy(s):
    codes = {'hopper':'W001','plunger':'W210','stopper':'W211','cap':'W310'}
    for name, amount in s.bins.items():
        if amount < s.config['low_levels'][name] and name not in s.refills:
            s.refills[name] = s.config['refill_delay_s']
            alarm(s, codes[name], None, name + ' low; refill requested', 'WARN')


def prediction(s):
    import numpy as np
    values = s.stations['S2'].forces
    if len(values) < 5:
        return None
    slope, intercept = np.polyfit(*zip(*values), 1)
    if slope <= 0:
        return None
    return max(0.0, float((160 - intercept) / slope - values[-1][0]))


def maintenance_policy(s):
    st = s.stations['S2']
    cycles = prediction(s)
    if (st.force is not None and st.force > 135) or (cycles is not None and cycles < 60):
        alarm(s, 'W202', 'S2', 'Tool wear high; plan a tool change.', 'WARN')
    if s.config['policy']['predictive_tool_change'] and not st.fault:
        st.pending_tool_change = any(a['code'] == 'W202' for a in active_alarms(s))
