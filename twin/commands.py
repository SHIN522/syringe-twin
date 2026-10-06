"""Validated operator commands and their audit records (brief section 8.4)."""
from .events import event, alarm, clear_alarm, trip_s2, wall_time


COMMANDS = {'start','stop','estop','reset','repair','tool_change',
            'inject_fault','refill','set_speed'}


def validate(cmd, user):
    if not isinstance(user, str) or not user.strip():
        raise ValueError('Enter an operator name before sending a command.')
    if cmd not in COMMANDS:
        raise ValueError('Unsupported command: ' + cmd)


def execute(s, cmd, args, user):
    validate(cmd, user)
    return audit(s, cmd, args, user, apply(s, cmd, args))


def audit(s, cmd, args, user, result):
    """Every operator command is logged, whether the twin or the PLC acts on it."""
    row = {'t': round(s.t, 3), 'wall': wall_time(), 'user': user.strip(),
           'cmd': cmd, 'args': args, 'result': result}
    s.commands.append(row)
    event(s, 'cmd', user=user.strip(), cmd=cmd, args=args, result=result)
    s.revision += 1
    return {'ok': True, 'message': result, 'revision': s.revision}


def apply(s, cmd, args):
    if cmd == 'start':
        if s.estop_active or s.estop_latched:
            raise ValueError('Release E-stop and reset its latch before Start.')
        s.run = True
        return 'Line started.'
    if cmd == 'stop':
        s.run = False
        return 'Line paused; parts and process progress retained.'
    if cmd == 'estop':
        active = args.get('active')
        if type(active) is not bool:
            raise ValueError('estop requires active: true or false.')
        s.estop_active = active
        if active:
            s.run, s.estop_latched = False, True
            alarm(s, 'F001', None, 'Emergency stop active.')
        return 'E-stop engaged.' if active else 'E-stop released; Reset then Start.'
    if cmd == 'reset':
        return reset(s)
    if cmd == 'inject_fault':
        if args.get('code') != 'F201':
            raise ValueError('Fault injection is available for F201 only.')
        check_injectable(s)
        trip_s2(s, injected=True)
        return 'Injected F201 at S2; affected unit marked injected.'
    if cmd == 'set_speed':
        x = args.get('x')
        if x not in (1,2,5,10,50) or isinstance(x, bool):
            raise ValueError('Speed must be 1, 2, 5, 10 or 50.')
        s.speed = int(x)
        return f'Simulation speed set to {x}×.'
    if cmd == 'refill':
        name = args.get('bin')
        if name not in s.bins:
            raise ValueError('Unknown material bin.')
        s.refills.setdefault(name, s.config['refill_delay_s'])
        return f'{name} refill requested; arrives in simulation time.'
    return maintenance(s, cmd, args)


def reset(s):
    if s.estop_active:
        return 'Reset ignored: physical E-stop is still active.'
    s.estop_latched = False
    clear_alarm(s, 'F001')
    st = s.stations['S2']
    if st.fault and st.tool_ok:
        resume_s2(s)
        return 'F201 cleared; S2 resumes at RETRACT.'
    if st.fault:
        return 'F201 remains latched: repair must finish before reset.'
    return 'Alarm reset complete. Start separately after E-stop recovery.'


def check_injectable(s):
    st = s.stations['S2']
    if st.pallet is None or st.step_i < 0 or st.done or st.fault or st.maintenance:
        raise ValueError('Inject F201 while S2 is processing a part.')


def resume_s2(s):
    """F201 cleared: S2 resumes at RETRACT; the affected unit flows on to inspection (D6)."""
    st = s.stations['S2']
    st.fault, st.step_i, st.elapsed, st.done = None, 2, 0.0, False
    clear_alarm(s, 'F201')
    event(s, 'maintenance', 'S2', action='reset_resume_retract')


def maintenance(s, cmd, args):
    if args.get('station') != 'S2':
        raise ValueError('Maintenance is implemented for station S2.')
    st = s.stations['S2']
    if cmd == 'repair':
        if not st.fault:
            raise ValueError('S2 is not faulted; use Tool change for planned work.')
        if st.maintenance or st.tool_ok:
            raise ValueError('Repair is already running or complete; reset after completion.')
        st.maintenance = 'repair'
        st.remaining = s.config['stations']['S2']['mttr_s']
        event(s, 'maintenance', 'S2', action='repair_started')
        return 'Repair started: 90 simulation seconds, then Reset.'
    if st.fault or st.maintenance:
        raise ValueError('Recover the fault before scheduling a tool change.')
    st.pending_tool_change = True
    event(s, 'maintenance', 'S2', action='tool_change_requested')
    return 'Tool change queued for S2’s next WAIT; duration 20 simulation seconds.'
