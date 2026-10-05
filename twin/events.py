"""Simulation-time events and latched alarm helpers (brief sections 8 and 11)."""
from datetime import datetime
from zoneinfo import ZoneInfo


def wall_time():
    return datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(timespec='seconds')


def event(s, kind, station=None, serial=None, **data):
    item = {'t': round(s.t, 3), 'type': kind, 'station': station,
            'serial': serial, **data}
    s.events.append(item)
    if serial in s.parts:
        s.parts[serial].events.append(item)
    return item


def alarm(s, code, station, text, sev='FAULT', injected=False):
    if any(a['code'] == code and a['t_cleared'] is None for a in s.alarms):
        return
    s.alarms.append({'code': code, 'station': station, 'sev': sev,
                     't_raised': round(s.t, 3), 't_cleared': None,
                     'text': text, 'injected': injected})
    event(s, 'alarm', station, code=code, action='raised', injected=injected)


def clear_alarm(s, code):
    for a in s.alarms:
        if a['code'] == code and a['t_cleared'] is None:
            a['t_cleared'] = round(s.t, 3)
            event(s, 'alarm', a['station'], code=code, action='cleared')


def active_alarms(s):
    return [a for a in s.alarms if a['t_cleared'] is None]


def trip_s2(s, injected=False):
    st = s.stations['S2']
    if st.fault:
        return
    st.fault, st.tool_ok = 'F201', False
    s.faults_s2 += 1
    serial = s.pallets.get(st.pallet)
    if serial:
        part = s.parts[serial]
        if injected:
            st.force = s.config['stations']['S2']['force']['trip'] + 1.0
            part.meas['force_N'] = st.force
        event(s, 'part', 'S2', serial, event='overload', injected=injected,
              force_N=st.force)
    alarm(s, 'F201', 'S2', 'Press overload. Repair, then reset.', injected=injected)
