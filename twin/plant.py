"""Process durations, motion and quality measurements (brief sections 3 and 4).

The controller authorizes processing and transfers; this module advances physics.
This MVP uses sequence actions rather than the complete frozen PLC I/O map.
"""
from .events import event, clear_alarm


def serial_at(s, name):
    return s.pallets.get(s.stations[name].pallet)


def advance_motion(s, dt):
    for tr in list(s.transfers):
        tr.remaining = max(0.0, tr.remaining - dt)
        if tr.remaining > 1e-8:
            continue
        if tr.destination == 'RETURN':
            s.empty.append(tr.pallet)
        elif tr.destination in s.buffers:
            s.buffers[tr.destination].append(tr.pallet)
        else:
            s.stations[tr.destination].pallet = tr.pallet
        event(s, 'part', tr.destination, s.pallets[tr.pallet], event='arrived')
        s.transfers.remove(tr)


def advance_refills(s, dt):
    for name in list(s.refills):
        s.refills[name] -= dt
        if s.refills[name] <= 1e-8:
            s.bins[name] = s.config['bins'][name]
            del s.refills[name]
            clear_alarm(s, {'hopper':'W001','plunger':'W210',
                            'stopper':'W211','cap':'W310'}[name])
            event(s, 'material', bin=name, action='refilled')


def advance_maintenance(s, name, dt):
    st = s.stations[name]
    if not st.maintenance:
        return
    st.remaining = max(0.0, st.remaining - dt)
    if st.remaining > 1e-8:
        return
    mode = st.maintenance
    st.maintenance = None
    st.tool_ok = True
    st.wear = 0.0
    st.forces.clear()
    st.pending_tool_change = False
    clear_alarm(s, 'W202')
    event(s, 'maintenance', name, action=mode + '_complete')


def quality_sample(s, name, step):
    serial = serial_at(s, name)
    if not serial:
        return
    p, r = s.parts[serial], s.rng[name]
    c, st = s.config['stations'][name], s.stations[name]
    if name == 'S1' and step == 'PRINT':
        p.meas['print_offset_mm'] = float(r.normal(0, c['print_sigma']))
    elif name == 'S2' and step == 'PRESS':
        f = c['force']
        st.force = float(f['base'] + f['wear_gain'] * st.wear + r.normal(0, f['sigma']))
        p.meas['force_N'] = st.force
        st.wear += c['wear_per_cycle']
        st.forces.append((st.cycles + 1, st.force))
    elif name == 'S3' and step == 'CAP_PRESS':
        p.meas['cap_ok'] = bool(r.random() < c['cap_probability'])
    elif name == 'S3' and step == 'LASER':
        p.meas['mark_grade'] = str(r.choice(list('ABCD'), p=c['mark_probabilities']))
    elif name == 'S4' and step == 'LEAK':
        low, high = s.config['stations']['S2']['force']['win']
        force = p.meas.get('force_N', low - 1)
        leak = r.normal(c['leak_base'], c['leak_sigma'])
        if not low <= force <= high:
            leak += r.normal(c['damaged_leak_base'], c['damaged_leak_sigma'])
        p.meas['leak_Pa_s'] = float(leak)


def advance_sequences(s, enabled, dt):
    for name in enabled:
        st = s.stations[name]
        steps = list(s.config['stations'][name]['steps'].items())
        if st.step_i < 0 or st.done:
            continue
        step, duration = steps[st.step_i]
        st.elapsed += dt
        if st.elapsed + 1e-8 < duration:
            continue
        quality_sample(s, name, step)
        event(s, 'part', name, serial_at(s, name), event='step_complete', step=step)
        st.elapsed = 0.0
        # Controller handles quality decisions, alarms and step transitions.
        st.done = True
