"""Python stand-in for plc/openplc/syringetwin.st, for bridge tests only.

Statement order and names follow the ST program so the two can be compared
line by line. The real controller is the ST program running in OpenPLC.
"""
MW = 1024
COILS = ('M_SYS_RUN', 'Q_LAMP_GREEN', 'Q_LAMP_AMBER', 'Q_LAMP_RED', 'Q_HORN', 'F201', 'F001',
         'F002', 'M_ANY_FAULT', 'F201_INJECTED', 'S2_RELEASE_PERMIT', 'M_S2_REPAIRED')
INPUTS = ('CMD_START', 'CMD_STOP', 'CMD_RESET', 'I_ESTOP_OK', 'I_S2_TOOL_OK', 'AI_S2_FORCE',
          'S2_PRESS_SEQ', 'GOOD_SEQ', 'REJECT_SEQ', 'HEARTBEAT', 'TWIN_WARN', 'ANY_BLOCKED',
          'S2_DONE', 'B3_ROOM', 'IN_SEQ', 'CMD_INJECT_F201')


class Ton:
    def __init__(self, pt):
        self.pt, self.et, self.q = pt, 0.0, False

    def __call__(self, inp, dt):
        self.et = min(self.pt, self.et + dt) if inp else 0.0
        self.q = inp and self.et >= self.pt


class SoftPlc:
    def __init__(self, scan_s=0.02):
        self.dt = scan_s
        self.v = dict.fromkeys(COILS, False)
        self.last = {'START': False, 'RESET': False, 'INJ': False, 'TOOL': False}
        self.seq = {'PRESS': 0, 'GOOD': 0, 'REJECT': 0, 'IN': 0, 'HB': 0}
        self.link_seen = False
        self.verdict = self.heartbeat = 0
        self.counters = {'C_IN': 0, 'C_GOOD': 0, 'C_REJECT': 0, 'C_BOX': 0, 'BOXES': 0}
        self.cu_last = dict.fromkeys(('C_IN', 'C_GOOD', 'C_REJECT', 'C_BOX'), False)
        self.blink_t1, self.blink_t2, self.t_wd = Ton(0.5), Ton(0.5), Ton(1.0)

    def _edge(self, key, value):
        rising = value and not self.last[key]
        self.last[key] = value
        return rising

    def _ctu(self, name, cu):
        if cu and not self.cu_last[name]:
            self.counters[name] += 1
        self.cu_last[name] = cu

    def __call__(self, server):
        signed = lambda x: x - 65536 if x >= 32768 else x
        i = {name: signed(server.hr[MW + n]) for n, name in enumerate(INPUTS)}
        v = self.v
        # IO_MAP
        start_re = self._edge('START', i['CMD_START'] != 0)
        reset_re = self._edge('RESET', i['CMD_RESET'] != 0)
        inject_re = self._edge('INJ', i['CMD_INJECT_F201'] != 0)
        tool_ok = i['I_S2_TOOL_OK'] != 0
        tool_ok_re = self._edge('TOOL', tool_ok)
        new = {}
        for key, name in (('GOOD', 'GOOD_SEQ'), ('REJECT', 'REJECT_SEQ'), ('IN', 'IN_SEQ'), ('HB', 'HEARTBEAT')):
            new[key] = i[name] != self.seq[key]
            self.seq[key] = i[name]
        new_press = i['S2_PRESS_SEQ'] != self.seq['PRESS']
        if new['HB']:
            self.link_seen = True
        self.heartbeat = 0 if self.heartbeat >= 30000 else self.heartbeat + 1
        # P5
        if new_press and i['AI_S2_FORCE'] > 1600:
            v['F201'], v['M_S2_REPAIRED'] = True, False
        if inject_re:
            v['F201'] = v['F201_INJECTED'] = True
            v['M_S2_REPAIRED'] = False
        if new_press:
            self.verdict = self.seq['PRESS'] = i['S2_PRESS_SEQ']
        # P8
        if v['F201'] and tool_ok_re:
            v['M_S2_REPAIRED'] = True
        if reset_re and v['F201'] and v['M_S2_REPAIRED'] and tool_ok:
            v['F201'] = v['M_S2_REPAIRED'] = v['F201_INJECTED'] = False
        self.t_wd(self.link_seen and not new['HB'], self.dt)
        if self.t_wd.q:
            v['F002'] = True
        if reset_re and not self.t_wd.q:
            v['F002'] = False
        # P1
        if i['I_ESTOP_OK'] == 0:
            v['F001'] = True
        if reset_re and i['I_ESTOP_OK'] != 0:
            v['F001'] = False
        v['M_ANY_FAULT'] = v['F001'] or v['F201'] or v['F002']
        v['M_SYS_RUN'] = ((start_re or v['M_SYS_RUN']) and i['CMD_STOP'] == 0
                          and not v['F001'] and not v['F002'])
        self.blink_t1(not self.blink_t2.q, self.dt)
        self.blink_t2(self.blink_t1.q, self.dt)
        v['Q_LAMP_RED'] = v['M_ANY_FAULT'] and self.blink_t1.q
        v['Q_HORN'] = v['M_ANY_FAULT']
        v['Q_LAMP_AMBER'] = not v['M_ANY_FAULT'] and (i['TWIN_WARN'] != 0 or i['ANY_BLOCKED'] != 0)
        v['Q_LAMP_GREEN'] = v['M_SYS_RUN'] and not v['M_ANY_FAULT'] and not v['Q_LAMP_AMBER']
        # P9
        self._ctu('C_IN', new['IN'])
        self._ctu('C_GOOD', new['GOOD'])
        self._ctu('C_REJECT', new['REJECT'])
        self._ctu('C_BOX', new['GOOD'])
        if self.counters['C_BOX'] >= 10:
            self.counters['BOXES'] += 1
            self.counters['C_BOX'] = 0
        # P2
        v['S2_RELEASE_PERMIT'] = (i['S2_DONE'] != 0 and i['B3_ROOM'] != 0
                                  and v['M_SYS_RUN'] and not v['F201'])
        for n, name in enumerate(COILS):
            server.coils[n] = v[name]
        c = self.counters
        server.hr[0:7] = [self.verdict & 0xFFFF, self.heartbeat, c['C_IN'], c['C_GOOD'],
                          c['C_REJECT'], c['C_BOX'], c['BOXES']]
