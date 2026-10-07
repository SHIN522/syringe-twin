"""Live 3D view of the twin in CoppeliaSim (read-only; the Python twin stays the source of truth).

Usage:
  1. Start the twin (launch.py, or python -m twin --profile demo). Use 1x-2x speed for the 3D view.
  2. python tools/coppelia_view.py --launch      (starts CoppeliaSim if it is not open)
     python tools/coppelia_view.py               (CoppeliaSim already open)

The cell is built in a Factory I/O-like style: roller conveyors with side rails,
machine frames over the line, photo-eye sensors, a control panel, a stack light
and a scoreboard. It mirrors /api/motion at ~20 Hz:
  * pallets glide between stations; each syringe gains its parts station by station;
  * housings take the machine-state colour; the S2 press ram strokes;
  * S4 shows the inspection result: PASS (green) or FAIL (red) lamp and syringe tint,
    a pusher diverts failed parts into the reject bin, good parts fill the packing box;
  * the scoreboard shows good / reject / yield / throughput / OEE and the last decision.
Only one viewer may run at a time. Loading another scene makes it rebuild.
--save writes sim/syringetwin_cell.ttt (a static snapshot of the layout).
"""
import argparse
import math
import os
import socket
import subprocess
import time
from pathlib import Path
import requests
from coppeliasim_zmqremoteapi_client import RemoteAPIClient

ROOT = Path(__file__).resolve().parents[1]
ZMQ_PORT = 23000  # CoppeliaSim's ZeroMQ remote API


def coppelia_executable():
    """CoppeliaSim on Windows (installer) or Linux (tarball in ~/CoppeliaSim*, see tools/ubuntu_coppelia.sh)."""
    if os.environ.get('COPPELIASIM_ROOT'):
        root = Path(os.environ['COPPELIASIM_ROOT'])
        return root / ('coppeliaSim.exe' if os.name == 'nt' else 'coppeliaSim.sh')
    if os.name == 'nt':
        return Path(r'C:\Program Files\CoppeliaRobotics\CoppeliaSimEdu\coppeliaSim.exe')
    found = sorted(Path.home().glob('CoppeliaSim*/coppeliaSim.sh'))
    return found[-1] if found else Path.home() / 'CoppeliaSim' / 'coppeliaSim.sh'


LOCK_PORT = 23990
X = {'IN': 0.0, 'B1': 1.2, 'S1': 2.4, 'B2': 3.6, 'S2': 4.8, 'B3': 6.0, 'S3': 7.2, 'B4': 8.4, 'S4': 9.6, 'OUT': 10.8}
STATIONS = ('IN', 'S1', 'S2', 'S3', 'S4', 'OUT')
LABELS = {'IN': 'IN - LOAD', 'S1': 'S1 - PRINT', 'S2': 'S2 - PRESS', 'S3': 'S3 - CAP', 'S4': 'S4 - INSPECT', 'OUT': 'OUT - PACK'}
BELT_Z, RETURN_Y, PALLET_Z = 0.55, -1.0, 0.57
QUEUE_X, QUEUE_PITCH = -0.25, 0.3
STATE_RGB = {'RUNNING': [0.25, 0.72, 0.42], 'STARVED': [0.70, 0.72, 0.70], 'BLOCKED': [0.95, 0.66, 0.15],
             'FAULT': [0.90, 0.22, 0.18], 'MAINT': [0.30, 0.55, 0.90], 'STOPPED': [0.40, 0.42, 0.41]}
TOOL = {'IN': ('box', [0.16, 0.16, 0.12]), 'S1': ('box', [0.22, 0.14, 0.08]), 'S2': ('ram', [0.10, 0.10, 0.34]),
        'S3': ('cyl', [0.07, 0.07, 0.16]), 'S4': ('cyl', [0.10, 0.10, 0.08]), 'OUT': ('box', [0.18, 0.18, 0.10])}
STAGE = {'IN': 1, 'B1': 1, 'S1': 1, 'B2': 2, 'S2': 2, 'B3': 3, 'S3': 3, 'B4': 4, 'S4': 4, 'OUT': 4}
BATCH_LUA = '''
function sysCall_init() end
function setPositions(handles, positions)
    for i = 1, #handles do sim.setObjectPosition(handles[i], positions[i], sim.handle_world) end
end
'''
FRAME, ROLLER, LEG, YELLOW = [0.22, 0.27, 0.34], [0.78, 0.80, 0.82], [0.30, 0.33, 0.38], [0.96, 0.76, 0.08]
PASS_RGB, FAIL_RGB, DIM = [0.10, 0.90, 0.30], [1.00, 0.15, 0.10], [0.16, 0.16, 0.16]


class View:
    def __init__(self, sim, text=None):
        self.sim, self.text = sim, text  # text: CoppeliaSim's textUtils module (labels), optional
        self.cache, self.shown = {}, {}
        self.root = None
        self.board, self.board_text = [], None
        self.batch, self.pending = None, {}

    # ---- primitives ------------------------------------------------------------
    def shape(self, kind, size, pos, rgb, alias, parent=None, orient=None):
        sim = self.sim
        h = sim.createPrimitiveShape(kind, size, 0)
        sim.setObjectAlias(h, alias)
        if orient:
            sim.setObjectOrientation(h, orient, sim.handle_world)
        sim.setObjectPosition(h, pos, sim.handle_world)
        sim.setShapeColor(h, None, sim.colorcomponent_ambient_diffuse, rgb)
        sim.setObjectParent(h, self.root if parent is None else parent, True)
        return h

    def box(self, size, pos, rgb, alias, parent=None):
        return self.shape(self.sim.primitiveshape_cuboid, size, pos, rgb, alias, parent)

    def cyl(self, size, pos, rgb, alias, parent=None, axis='z'):
        orient = {'z': None, 'x': [0, math.pi / 2, 0], 'y': [math.pi / 2, 0, 0]}[axis]
        return self.shape(self.sim.primitiveshape_cylinder, size, pos, rgb, alias, parent, orient)

    def label(self, text, pos, height=0.075, rgb=(0.97, 0.98, 0.97)):
        """Text facing -y (CoppeliaSim textUtils); returns the handle, or None if unavailable."""
        if not self.text:
            return None
        try:
            h = self.text.generateTextShape(text, list(rgb), height, True)
            self.sim.setObjectOrientation(h, [math.pi / 2, 0, 0], self.sim.handle_world)
            self.sim.setObjectPosition(h, pos, self.sim.handle_world)
            self.sim.setObjectParent(h, self.root, True)
            return h
        except Exception:
            self.text = None  # labels are cosmetic; keep the view running
            return None

    def conveyor(self, name, start, end, fixed, axis='x', pitch=0.15):
        """Roller conveyor: side rails, rollers (grouped into one shape), legs with feet."""
        sim = self.sim
        length = end - start
        mid = (start + end) / 2
        at = (lambda a, b, z: [a, b, z]) if axis == 'x' else (lambda a, b, z: [b, a, z])
        size = (lambda l, w, h: [l, w, h]) if axis == 'x' else (lambda l, w, h: [w, l, h])
        for side in (-0.19, 0.19):
            self.box(size(length, 0.04, 0.09), at(mid, fixed + side, BELT_Z - 0.01), FRAME, f'{name}_Rail')
        rollers = []
        n = int(length / pitch)
        for i in range(n):
            a = start + pitch * (i + 0.5)
            rollers.append(self.cyl([0.05, 0.05, 0.34], at(a, fixed, BELT_Z - 0.025), ROLLER, f'{name}_Roller',
                                    axis='y' if axis == 'x' else 'x'))
        if len(rollers) > 1:
            grouped = sim.groupShapes(rollers, False)
            sim.setObjectAlias(grouped, f'{name}_Rollers')
        a = start + 0.1
        while a < end:
            for side in (-0.17, 0.17):
                self.box(size(0.05, 0.05, BELT_Z - 0.06), at(a, fixed + side, (BELT_Z - 0.06) / 2), LEG, f'{name}_Leg')
                self.box(size(0.12, 0.12, 0.01), at(a, fixed + side, 0.005), LEG, f'{name}_Foot')
            self.box(size(0.04, 0.34, 0.04), at(a, fixed, 0.18), LEG, f'{name}_Brace')
            a += 1.0

    # ---- scene -----------------------------------------------------------------
    def build(self):
        sim = self.sim
        old = sim.getObject('/SyringeTwin', {'noError': True})
        if old != -1:
            sim.removeObjects(sim.getObjectsInTree(old))
        self.cache, self.shown, self.board, self.board_text = {}, {}, [], None
        self.batch, self.pending = None, {}
        self.root = sim.createDummy(0.05)
        sim.setObjectAlias(self.root, 'SyringeTwin')
        # With the simulation stopped CoppeliaSim idles at ~8 fps, which makes motion look choppy; 0 = render as fast as possible.
        sim.setInt32Param(sim.intparam_idle_fps, 0)  # 0 = unlimited
        # One in-scene Lua helper applies all moving positions in a single remote call per frame.
        try:
            self.batch = sim.createScript(sim.scripttype_customization, BATCH_LUA, 0, 'lua')
            sim.setObjectParent(self.batch, self.root, False)
        except Exception:
            self.batch = None
        for param, rgb in (('arrayparam_background_color1', [0.93, 0.95, 0.97]),
                           ('arrayparam_background_color2', [0.80, 0.85, 0.90])):
            try:
                sim.setArrayParam(getattr(sim, param), rgb)
            except Exception:
                pass
        # hall: concrete floor, hazard lines, walkway, back wall with a stripe
        self.box([18.0, 7.0, 0.02], [5.4, -0.2, -0.011], [0.58, 0.60, 0.60], 'Floor')
        for y in (-1.55, 0.95):
            self.box([13.6, 0.08, 0.004], [5.4, y, 0.002], YELLOW, 'HazardLine')
        self.box([13.6, 0.9, 0.003], [5.4, -2.3, 0.0015], [0.45, 0.55, 0.62], 'Walkway')
        self.box([18.0, 0.12, 6.0], [5.4, 2.8, 3.0], [0.86, 0.88, 0.90], 'BackWall')
        self.box([18.0, 0.13, 0.35], [5.4, 2.79, 0.9], [0.18, 0.38, 0.62], 'WallStripe')
        # conveyors (main line, return line, end transfers)
        self.conveyor('Main', -0.7, 11.5, 0.0)
        self.conveyor('Return', -0.7, 11.5, RETURN_Y)
        self.conveyor('TransferIn', RETURN_Y + 0.2, -0.2, -0.55, axis='y')
        self.conveyor('TransferOut', RETURN_Y + 0.2, -0.2, 11.35, axis='y')
        for name in ('B1', 'B2', 'B3', 'B4'):  # accumulation zones, marked on the rails
            for side in (-0.215, 0.215):
                self.box([0.62, 0.012, 0.095], [X[name], side, BELT_Z - 0.01], YELLOW, f'Buffer_{name}')
        # machines straddle the line: frame, state-coloured housing, name plate, lamp, tool
        self.housing, self.lamp, self.tool, self.beam = {}, {}, {}, {}
        for name in STATIONS:
            x = X[name]
            for y in (-0.32, 0.32):
                self.box([0.10, 0.10, 1.25], [x, y, 0.625], FRAME, f'Pillar_{name}')
            self.housing[name] = self.box([0.70, 0.80, 0.32], [x, 0, 1.41], STATE_RGB['STOPPED'], f'Housing_{name}')
            self.label(LABELS[name], [x, -0.405, 1.41])
            self.lamp[name] = self.cyl([0.10, 0.10, 0.10], [x + 0.22, 0.25, 1.62], STATE_RGB['STOPPED'], f'Lamp_{name}')
            kind, size = TOOL[name]
            z = 1.25 - size[2] / 2
            make = self.cyl if kind in ('cyl', 'ram') else self.box
            self.tool[name] = make(size, [x, 0, z], [0.88, 0.88, 0.90], f'Tool_{name}')
            # photo-eye at the station entry: emitter, reflector and a beam lit while a pallet is present
            ex = x - 0.2
            self.box([0.04, 0.04, 0.20], [ex, -0.26, BELT_Z + 0.10], LEG, f'EyePost_{name}')
            self.box([0.06, 0.05, 0.05], [ex, -0.26, BELT_Z + 0.09], [0.95, 0.45, 0.05], f'Eye_{name}')
            self.box([0.04, 0.02, 0.05], [ex, 0.26, BELT_Z + 0.09], [0.85, 0.85, 0.85], f'Reflector_{name}')
            self.beam[name] = self.cyl([0.008, 0.008, 0.50], [ex, 0, BELT_Z + 0.09], [1.0, 0.1, 0.1], f'Beam_{name}', axis='y')
        self.ram_up = 1.25 - TOOL['S2'][1][2] / 2
        # S4 inspection: result lamp, vision light, pusher, reject bin with a pile
        self.result = self.cyl([0.16, 0.16, 0.10], [X['S4'] - 0.15, 0.0, 1.62], DIM, 'S4_ResultLamp')
        self.vision = self.cyl([0.22, 0.22, 0.42], [X['S4'], 0, BELT_Z + 0.34], [1.0, 0.95, 0.55], 'S4_VisionLight')
        sim.setShapeColor(self.vision, None, sim.colorcomponent_transparency, [0.55])
        self.pusher_out, self.pusher_in = -0.13, -0.52
        self.box([0.10, 0.30, 0.12], [X['S4'], -0.72, BELT_Z + 0.06], FRAME, 'S4_PusherBody')
        self.pusher = self.box([0.18, 0.06, 0.10], [X['S4'], self.pusher_in, BELT_Z + 0.07], [0.95, 0.45, 0.05], 'S4_Pusher')
        bin_x = X['S4']
        self.box([0.46, 0.46, 0.04], [bin_x, 0.66, 0.02], [0.75, 0.20, 0.15], 'RejectBinBase')
        for dx, dy, sx, sy in ((0, 0.22, 0.46, 0.02), (0, -0.22, 0.46, 0.02), (0.22, 0, 0.02, 0.46), (-0.22, 0, 0.02, 0.46)):
            self.box([sx, sy, 0.34], [bin_x + dx, 0.66 + dy, 0.17], [0.85, 0.25, 0.18], 'RejectBinWall')
        self.label('REJECT', [bin_x, 0.43, 0.25], height=0.06)
        self.reject_pile = [self.cyl([0.05, 0.05, 0.16], [bin_x - 0.12 + 0.12 * (i % 3), 0.58 + 0.08 * ((i // 3) % 2), 0.07 + 0.05 * (i // 6)],
                                     [0.95, 0.55, 0.52], f'RejectPart_{i}', axis='x') for i in range(9)]
        # OUT packing: open box with ten slots, finished boxes stacked beside it
        box_x = X['OUT']
        self.box([0.56, 0.36, 0.04], [box_x, 0.72, 0.30], [0.72, 0.56, 0.34], 'PackBoxBase')
        self.box([0.56, 0.36, 0.28], [box_x, 0.72, 0.14], [0.68, 0.52, 0.30], 'PackBoxBody')
        self.label('GOOD', [box_x, 0.53, 0.18], height=0.06)
        self.pack = [self.cyl([0.045, 0.045, 0.14], [box_x - 0.2 + 0.1 * (i % 5), 0.66 + 0.12 * (i // 5), 0.39],
                              [0.80, 0.96, 0.82], f'PackedSyringe_{i}') for i in range(10)]
        self.closed = [self.box([0.30, 0.24, 0.18], [box_x + 0.75 + 0.32 * (i % 2), 0.72, 0.09 + 0.19 * (i // 2)],
                                [0.66, 0.50, 0.30], f'ClosedBox_{i}') for i in range(6)]
        # control panel and stack light
        px = -1.45
        self.box([0.40, 0.30, 1.15], [px, 0.45, 0.575], [0.28, 0.32, 0.38], 'ControlPanel')
        self.label('CONTROL', [px, 0.295, 1.05], height=0.05)
        self.btn_start = self.cyl([0.07, 0.07, 0.03], [px - 0.1, 0.29, 0.85], DIM, 'Btn_Start', axis='y')
        self.btn_stop = self.cyl([0.07, 0.07, 0.03], [px + 0.1, 0.29, 0.85], DIM, 'Btn_Stop', axis='y')
        self.btn_estop = self.cyl([0.12, 0.12, 0.05], [px, 0.28, 0.65], [0.55, 0.08, 0.06], 'Btn_EStop', axis='y')
        self.box([0.18, 0.02, 0.18], [px, 0.30, 0.65], YELLOW, 'EStopPlate')
        # PLC cabinet: LEDs show the controller's own coils (OpenPLC over Modbus in PLC mode)
        cx = -2.25
        self.box([0.55, 0.32, 1.50], [cx, 0.45, 0.75], [0.62, 0.65, 0.68], 'PLC_Cabinet')
        self.box([0.47, 0.02, 0.50], [cx, 0.285, 1.05], [0.20, 0.22, 0.25], 'PLC_Rack')
        for i in range(5):  # I/O modules on the DIN rail
            self.box([0.07, 0.025, 0.30], [cx - 0.18 + 0.09 * i, 0.272, 1.05], [0.12, 0.30, 0.55] if i == 0 else [0.32, 0.34, 0.37], 'PLC_Module')
        self.label('OPENPLC', [cx, 0.285, 1.42], height=0.07)
        self.plc_led = {name: self.cyl([0.06, 0.06, 0.03], [cx - 0.15 + 0.15 * i, 0.272, 0.70], DIM, f'PLC_LED_{name}', axis='y')
                        for i, name in enumerate(('RUN', 'FAULT', 'LINK'))}
        for i, name in enumerate(('RUN', 'FAULT', 'LINK')):
            self.label(name, [cx - 0.15 + 0.15 * i, 0.285, 0.60], height=0.035)
        self.plc_label = None
        pole = [11.95, 0.55]
        self.cyl([0.05, 0.05, 1.5], [*pole, 0.75], LEG, 'TowerPole')
        self.tower = {c: self.cyl([0.16, 0.16, 0.13], [*pole, 1.57 + 0.14 * i], DIM, f'Tower_{c}')
                      for i, c in enumerate(('GREEN', 'AMBER', 'RED'))}
        # scoreboard on the back wall
        self.box([6.4, 0.05, 1.5], [5.4, 2.72, 2.45], [0.10, 0.12, 0.14], 'Scoreboard')
        self.label('SYRINGETWIN  -  GROUP 07 DIGITAL TWIN', [5.4, 2.68, 3.35], height=0.14, rgb=(0.20, 0.25, 0.30))
        # ten pallets, each carrying the syringe parts it has received so far
        self.pallets = {}
        for pid in range(1, 11):
            start = [0.1 + 0.3 * (pid - 1), RETURN_Y, PALLET_Z]
            base = self.box([0.24, 0.24, 0.04], start, [0.30, 0.42, 0.58], f'Pallet_{pid}')
            z, x0 = PALLET_Z + 0.055, start[0]
            parts = {'barrel': self.cyl([0.05, 0.05, 0.17], [x0, RETURN_Y, z], [0.95, 0.96, 0.97], f'Barrel_{pid}', base, 'x'),
                     'print': self.cyl([0.054, 0.054, 0.05], [x0 + 0.02, RETURN_Y, z], [0.18, 0.33, 0.78], f'Print_{pid}', base, 'x'),
                     'plunger': self.cyl([0.022, 0.022, 0.12], [x0 - 0.12, RETURN_Y, z], [0.22, 0.22, 0.25], f'Plunger_{pid}', base, 'x'),
                     'cap': self.cyl([0.03, 0.03, 0.05], [x0 + 0.11, RETURN_Y, z], [0.95, 0.52, 0.12], f'Cap_{pid}', base, 'x')}
            self.pallets[pid] = (base, parts)
            self.shown[pid] = list(start)
        try:
            sim.cameraFitToView(0, sim.getObjectsInTree(self.root), 3, 0.8)
        except Exception:
            pass

    def alive(self):
        try:
            return self.root is not None and self.sim.isHandle(self.root)
        except Exception:
            return False

    # ---- cached updates (only send what changed) --------------------------------
    def put(self, key, fn, value):
        if self.cache.get(key) != value:
            self.cache[key] = value
            fn(value)

    def color(self, h, rgb):
        self.put(('c', h), lambda v: self.sim.setShapeColor(h, None, self.sim.colorcomponent_ambient_diffuse, list(v)),
                 tuple(round(c, 3) for c in rgb))

    def position(self, h, xyz):
        def queue(v):
            self.pending[h] = list(v)
        self.put(('p', h), queue, tuple(round(c, 3) for c in xyz))

    def flush(self):
        """Send this frame's position changes: one batched call, or one call each as a fallback."""
        if not self.pending:
            return
        handles, positions = list(self.pending), list(self.pending.values())
        self.pending = {}
        if self.batch is not None:
            try:
                self.sim.callScriptFunction('setPositions', self.batch, handles, positions)
                return
            except Exception:
                self.batch = None
        for h, xyz in zip(handles, positions):
            self.sim.setObjectPosition(h, xyz, self.sim.handle_world)

    def visible(self, h, on):
        self.put(('v', h), lambda v: self.sim.setObjectInt32Param(h, self.sim.objintparam_visibility_layer, 1 if v else 0), bool(on))

    def scoreboard(self, lines):
        """Regenerate only the scoreboard lines whose text changed (3D text is costly to build)."""
        if not self.text:
            return
        if self.board_text is None:
            self.board_text, self.board = [None] * len(lines), [None] * len(lines)
        for i, line in enumerate(lines):
            if line == self.board_text[i]:
                continue
            if self.board[i] is not None:
                try:
                    self.sim.removeObjects(self.sim.getObjectsInTree(self.board[i]))
                except Exception:
                    pass
            text, rgb = line
            self.board[i] = self.label(text, [5.4, 2.68, 2.95 - 0.42 * i], height=0.20, rgb=rgb)
            self.board_text[i] = line


# ---- mapping twin state to positions ------------------------------------------
def slot(name, index=0):
    if name in ('B1', 'B2', 'B3', 'B4'):
        return [X[name] + (0.15 if index == 0 else -0.15), 0.0, PALLET_Z]  # front slot is downstream
    return [X[name], 0.0, PALLET_Z]


def along_return(frac, start_x, tail_x):
    """S4/OUT → across to the return line → back to the tail of the empty-pallet queue."""
    legs = [abs(RETURN_Y), max(0.0, start_x - tail_x)]
    d = frac * sum(legs)
    if d < legs[0]:
        return [start_x, -d, PALLET_Z]
    return [start_x - (d - legs[0]), RETURN_Y, PALLET_Z]


def targets(data, elapsed):
    s, m = data['snapshot'], data['meta']
    speed = s['speed'] if s['run'] else 0
    reverse = {serial: int(pid) for pid, serial in m['pallets'].items() if serial}
    busy = {tr['pallet'] for tr in m['transfers']} | {m['station_progress'][n]['pallet'] for n in STATIONS}
    queued = [pid for pid in range(1, 11) if pid not in busy and not m['pallets'].get(str(pid))]
    tail_x = QUEUE_X + QUEUE_PITCH * len(queued)
    where = {}
    for name in STATIONS:
        pid = m['station_progress'][name]['pallet']
        if pid is not None:
            where[pid] = (slot(name), STAGE[name])
    for name, serials in s['buffers'].items():
        for i, serial in enumerate(serials):
            if serial in reverse:
                where[reverse[serial]] = (slot(name, i), STAGE[name])
    for tr in m['transfers']:
        frac = max(0.0, min(1.0, 1 - (tr['remaining'] - elapsed * speed) / tr['total']))
        src = slot(tr['source'])
        if tr['destination'] == 'RETURN':
            where[tr['pallet']] = (along_return(frac, src[0], tail_x), 0)
        else:
            inbound = [t['pallet'] for t in m['transfers'] if t['destination'] == tr['destination']]
            index = len(s['buffers'].get(tr['destination'], [])) + inbound.index(tr['pallet'])
            dst = slot(tr['destination'], min(index, 1))
            where[tr['pallet']] = ([a + (b - a) * frac for a, b in zip(src, dst)], STAGE.get(tr['source'], 1))
    order = m.get('empty_queue') or range(1, 11)  # real queue order when the twin provides it
    queue = [pid for pid in order if pid not in where] + [pid for pid in range(1, 11) if pid not in where and pid not in order]
    for k, pid in enumerate(queue):  # empty pallets queue on the return line, front nearest IN
        where[pid] = ([QUEUE_X + QUEUE_PITCH * k, RETURN_Y, PALLET_Z], 0)
    return where


def step_fraction(data, name, elapsed):
    p = data['meta']['station_progress'][name]
    speed = data['snapshot']['speed'] if data['snapshot']['run'] else 0
    if not p.get('duration'):
        return 0.0
    return min(1.0, ((p.get('elapsed') or 0) + elapsed * speed) / p['duration'])


def frame(view, data, elapsed, dt):
    s, m = data['snapshot'], data['meta']
    parts = m.get('parts', {})
    for name in STATIONS:
        st = s['stations'][name]
        rgb = STATE_RGB.get(st['state'], STATE_RGB['STOPPED'])
        view.color(view.housing[name], rgb)
        view.color(view.lamp[name], [min(1, c * 1.15) for c in rgb])
        view.visible(view.beam[name], m['station_progress'][name]['pallet'] is not None)
    blink = (time.time() % 1.0) < 0.5
    for colour, h in view.tower.items():
        on = s['lamp'] == colour and (colour != 'RED' or blink)
        lit = {'GREEN': [0.1, 0.95, 0.3], 'AMBER': [1.0, 0.72, 0.05], 'RED': [1.0, 0.12, 0.08]}[colour]
        view.color(h, lit if on else DIM)
    # control panel: run (green), stopped (red), E-stop latched (flashing mushroom)
    view.color(view.btn_start, [0.1, 0.95, 0.3] if s['run'] else DIM)
    view.color(view.btn_stop, [1.0, 0.2, 0.15] if not s['run'] else DIM)
    view.color(view.btn_estop, [1.0, 0.08, 0.05] if m.get('estop_latched') and blink else [0.55, 0.08, 0.06])
    # PLC cabinet LEDs: real PLC coils in PLC mode, the twin's equivalent state otherwise
    plc = m.get('plc') or {'mode': 'internal'}
    if plc.get('mode') == 'plc':
        coils = plc.get('coils') or {}
        alive = plc.get('link_ok') and not plc.get('link_fault')
        run, fault, link = alive and coils.get('M_SYS_RUN'), coils.get('M_ANY_FAULT') or not alive, alive
    else:
        run, fault, link = s['run'], any(a['code'] in ('F001', 'F201') for a in s.get('alarms', [])), False
    view.color(view.plc_led['RUN'], [0.1, 0.95, 0.3] if run else DIM)
    view.color(view.plc_led['FAULT'], [1.0, 0.12, 0.08] if fault and blink else DIM)
    view.color(view.plc_led['LINK'], [0.2, 0.55, 1.0] if link and blink else DIM)
    # S2 press ram: down during PRESS, held during INSERT, up during RETRACT
    frac = step_fraction(data, 'S2', elapsed)
    drop = {'PRESS': frac, 'INSERT': 1.0, 'RETRACT': 1 - frac}.get(s['stations']['S2']['step'], 0.0) * 0.28
    view.position(view.tool['S2'], [X['S2'], 0, view.ram_up - drop])
    # S4 inspection: vision light during VISION, PASS/FAIL lamp, pusher diverts FAIL parts
    s4 = s['stations']['S4']
    status = parts.get(s4['part'], {}).get('status') if s4['part'] else None
    view.visible(view.vision, s4['step'] == 'VISION')
    view.color(view.result, PASS_RGB if status == 'PASS' else FAIL_RGB if status == 'FAIL' else DIM)
    push = step_fraction(data, 'S4', elapsed) if (status == 'FAIL' and s4['step'] == 'DIVERT_PASS') else 0.0
    push = math.sin(math.pi * push)  # out and back during the divert step
    view.position(view.pusher, [X['S4'], view.pusher_in + (view.pusher_out - view.pusher_in) * push, BELT_Z + 0.07])
    # bins: rejects pile up (emptied every 10), good syringes fill the box, finished boxes stack
    counts = s.get('counts', {})
    for i, h in enumerate(view.reject_pile):
        view.visible(h, i < counts.get('reject', 0) % 10)
    for i, h in enumerate(view.pack):
        view.visible(h, i < counts.get('good', 0) % 10)
    for i, h in enumerate(view.closed):
        view.visible(h, i < min(counts.get('boxes', 0), len(view.closed)))
    # pallets glide towards their true positions (display smoothing only)
    alpha = 1 - math.exp(-dt * 10)
    for pid, (target, stage) in targets(data, elapsed).items():
        base, items = view.pallets[pid]
        shown = view.shown[pid]
        if math.dist(shown, target) > 3:
            shown[:] = target
        else:
            shown[:] = [a + (b - a) * alpha for a, b in zip(shown, target)]
        serial = m['pallets'].get(str(pid))
        if not serial:
            stage = 0  # empty pallet
        view.position(base, shown)
        decided = parts.get(serial, {}).get('status') if serial else None
        view.color(items['barrel'], [0.70, 1.0, 0.72] if decided == 'PASS' else [1.0, 0.55, 0.50] if decided == 'FAIL'
                   else [0.95, 0.96, 0.97])
        view.visible(items['barrel'], stage >= 1)
        view.visible(items['print'], stage >= 2)
        view.visible(items['plunger'], stage >= 3)
        view.visible(items['cap'], stage >= 4)


def board_lines(data):
    c, k = data['snapshot'].get('counts', {}), data.get('kpi', {})
    # The CoppeliaSim 3D font has letters and digits only: no %, / or #.
    pct = lambda v: 'NA' if v is None else f'{v * 100:.0f} PCT'
    last = data['meta'].get('last_decision')
    verdict = 'NONE YET' if not last else f"SYR {last['serial'].replace('SYR-B07-', '')} {last['status']}" + \
        (f" {' '.join(last['codes'])}" if last['codes'] else '')
    colour = PASS_RGB if last and last['status'] == 'PASS' else FAIL_RGB if last else (0.9, 0.9, 0.9)
    return ((f"GOOD {c.get('good', 0)}    REJECT {c.get('reject', 0)}    YIELD {pct(k.get('Q'))}", (0.92, 0.95, 0.92)),
            (f"THROUGHPUT {k.get('th_ph', 0):.0f} PER HOUR    OEE {pct(k.get('oee_win'))}", (0.92, 0.95, 0.92)),
            (f'LAST INSPECTION  {verdict}', tuple(colour)))


# ---- process ---------------------------------------------------------------------
def single_instance():
    lock = socket.socket()
    try:
        lock.bind(('127.0.0.1', LOCK_PORT))
    except OSError:
        raise SystemExit('Another coppelia_view.py is already running; stop it first (two viewers fight over the scene).')
    return lock


def connect(launch):
    with socket.socket() as probe:
        running = probe.connect_ex(('127.0.0.1', ZMQ_PORT)) == 0
    if launch and not running:
        exe = coppelia_executable()
        if not exe.is_file():
            raise SystemExit(f'CoppeliaSim not found at {exe}; set COPPELIASIM_ROOT, '
                             'or start it manually and run without --launch.')
        subprocess.Popen([str(exe)], cwd=str(exe.parent),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('Starting CoppeliaSim…', flush=True)
        time.sleep(12)
    client = RemoteAPIClient()
    try:
        text = client.require('textUtils')
    except Exception:
        text = None
    return client.require('sim'), text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    parser.add_argument('--launch', action='store_true', help='start CoppeliaSim if it is not running')
    parser.add_argument('--save', action='store_true', help='also save sim/syringetwin_cell.ttt')
    args = parser.parse_args()
    _lock = single_instance()
    sim, text = connect(args.launch)
    view = View(sim, text)
    print('Building the cell…', flush=True)
    view.build()
    if args.save:
        (ROOT / 'sim').mkdir(exist_ok=True)
        sim.saveScene(str(ROOT / 'sim' / 'syringetwin_cell.ttt'))
        print('Saved sim/syringetwin_cell.ttt', flush=True)
    print(f'Mirroring {args.api} in CoppeliaSim. Ctrl+C to stop (the scene stays).', flush=True)
    data, fetched, last, checked, boarded, failures = None, 0.0, time.monotonic(), 0.0, 0.0, 0
    endpoint = '/api/motion'
    try:
        while True:
            now = time.monotonic()
            if now - checked > 1.0:
                checked = now
                if not view.alive():
                    print('Scene changed; rebuilding the cell.', flush=True)
                    view.build()
            if now - fetched >= 0.05:
                try:
                    response = requests.get(args.api + endpoint, timeout=2)
                    if response.status_code == 404 and endpoint == '/api/motion':
                        endpoint = '/api/live'  # twin without the motion endpoint
                        continue
                    data = response.json()
                    fetched, failures = now, 0
                except (requests.RequestException, ValueError):
                    failures += 1
                    if failures == 1:
                        print('Twin not reachable at', args.api, '- start it; retrying…', flush=True)
                    time.sleep(1)
                    continue
            if data:
                frame(view, data, now - fetched, now - last)
                view.flush()
                if now - boarded > 2.0:
                    boarded = now
                    view.scoreboard(board_lines(data))
            last = now
            time.sleep(0.03)
    except KeyboardInterrupt:
        print('Stopped.')


if __name__ == '__main__':
    main()
