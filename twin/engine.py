"""Fixed-step engine, with pacing outside the model (brief section 7)."""
from dataclasses import asdict
from .model import new_state
from .events import active_alarms, wall_time
from .control import scan, material_policy, maintenance_policy
from .plant import advance_motion, advance_sequences, advance_refills, advance_maintenance
from .kpi import counts, calculate, oee_counters
from .commands import execute


class Engine:
    def __init__(self, config=None, state=None):
        # A supplied state lets the what-if sandbox run a copy of the live twin.
        self.state = state if state is not None else new_state(config)

    def tick(self):
        s, dt = self.state, self.state.config['dt']
        if s.run:
            s.planned_time += dt
            st = s.stations['S2']
            st.unplanned += dt if st.fault else 0
            st.planned += dt if st.maintenance == 'tool_change' else 0
            advance_motion(s, dt)
            advance_refills(s, dt)
            for name in s.stations:
                advance_maintenance(s, name, dt)
            material_policy(s)
        enabled = scan(s)
        if s.run:
            advance_sequences(s, enabled, dt)
            # Prediction needs updating only on a new press sample, not every tick.
            st = s.stations['S2']
            if st.done and st.step_i == 0:
                maintenance_policy(s)
        s.wip_integral += counts(s)['wip'] * dt
        if round(s.t / dt) % round(10 / dt) == 0:
            s.oee_samples.append(oee_counters(s))
        s.t = round(s.t + dt, 6)

    def advance(self, duration_s):
        for _ in range(round(duration_s / self.state.config['dt'])):
            self.tick()

    def command(self, cmd, args=None, user='Operator'):
        return execute(self.state, cmd, args or {}, user)

    def snapshot(self):
        s = self.state
        active = active_alarms(s)
        fault = any(a['sev'] == 'FAULT' for a in active)
        warning = any(a['sev'] == 'WARN' for a in active)
        blocked = any(st.state == 'BLOCKED' for st in s.stations.values())
        lamp = 'RED' if fault else 'AMBER' if warning or blocked else 'GREEN' if s.run else 'OFF'
        station_data = {}
        for name, st in s.stations.items():
            steps = list(s.config['stations'][name]['steps'])
            step = steps[st.step_i] if 0 <= st.step_i < len(steps) else 'RELEASE' if st.done else 'WAIT'
            station_data[name] = {'state': st.state, 'reason': st.reason, 'step': step,
                'part': s.pallets.get(st.pallet), 'cycles': st.cycles, 'last_ct': st.last_ct,
                'down_s': st.unplanned, 'wear': st.wear if name == 'S2' else None,
                'force': st.force if name == 'S2' else None}
        return {'t': s.t, 'wall': wall_time(), 'run': s.run, 'speed': s.speed, 'lamp': lamp,
                'stations': station_data, 'buffers': {b:[s.pallets[p] for p in ps] for b,ps in s.buffers.items()},
                'bins': dict(s.bins), 'counts': counts(s),
                'alarms': [{'code':a['code'],'sev':a['sev'],'since':a['t_raised'],'text':a['text']}
                           for a in active]}

    def payload(self):
        s = self.state
        station_progress = {}
        for name, st in s.stations.items():
            durations = list(s.config['stations'][name]['steps'].values())
            duration = durations[st.step_i] if 0 <= st.step_i < len(durations) else None
            station_progress[name] = {
                'pallet': st.pallet, 'elapsed': st.elapsed, 'duration': duration,
                'progress': min(1.0, st.elapsed / duration) if duration else None,
            }
        return {'snapshot': self.snapshot(), 'kpi': calculate(s),
                'meta': {'estop_active': s.estop_active, 'estop_latched': s.estop_latched,
                         'revision': s.revision, 'model': 'SyringeTwin v1.0', 'profile': s.config.get('label'),
                         'material_capacity': s.config['bins'], 'buffer_capacity': s.config['buffers'],
                         'refills': s.refills, 'maintenance_remaining_s': s.stations['S2'].remaining,
                         'tool_ok': s.stations['S2'].tool_ok, 'tool_change_queued': s.stations['S2'].pending_tool_change,
                         'transfers': [asdict(tr) for tr in s.transfers],
                         'station_progress': station_progress, 'pallets': dict(s.pallets),
                         'empty_pallets': len(s.empty), 'decisions': s.decisions}}
