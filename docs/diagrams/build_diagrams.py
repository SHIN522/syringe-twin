"""Generate the five engineering diagrams as editable draw.io files.

Usage: python docs/diagrams/build_diagrams.py   (writes docs/diagrams/*.drawio)
Open any file in draw.io / app.diagrams.net to edit or export PNG/SVG/PDF.
Labels and numbers follow config/line.yaml, docs/plc/PLC_SPEC.md and the code.
"""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = 'fontFamily=Segoe UI;fontSize=11;'
# Layer palette: twin/MES green, control blue, operator amber, fault red, neutral grey.
C = {
    'twin': 'fillColor=#E8F3E0;strokeColor=#46733D;fontColor=#1F3A1A;',
    'plc': 'fillColor=#E3EEF8;strokeColor=#3F6B93;fontColor=#1D3550;',
    'ops': 'fillColor=#FBF3DF;strokeColor=#9A7A2C;fontColor=#4A3A10;',
    'fault': 'fillColor=#FDECE8;strokeColor=#B0563F;fontColor=#5A2215;',
    'warn': 'fillColor=#FFF4D6;strokeColor=#C08A1E;fontColor=#4A3A10;',
    'grey': 'fillColor=#F4F5F2;strokeColor=#7A887F;fontColor=#2A332D;',
    'white': 'fillColor=#FFFFFF;strokeColor=#9AA89C;fontColor=#2A332D;',
}


class Diagram:
    def __init__(self, name, width=1600, height=1000):
        self.name, self.width, self.height = name, width, height
        self.cells, self.n = [], 1
        self.oy = 0  # vertical offset for top-level shapes drawn after the title

    def _id(self):
        self.n += 1
        return f'c{self.n}'

    def box(self, label, x, y, w, h, kind='white', extra='', parent='1'):
        cid = self._id()
        y += self.oy if parent == '1' else 0
        style = f'rounded=1;whiteSpace=wrap;html=1;arcSize=8;{FONT}{C[kind]}{extra}'
        self.cells.append(f'<mxCell id="{cid}" value="{escape(label)}" style="{style}" vertex="1" parent="{parent}">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def lane(self, label, x, y, w, h, kind):
        cid = self._id()
        style = (f'swimlane;html=1;startSize=26;horizontal=1;rounded=1;arcSize=2;{FONT}fontSize=12;fontStyle=1;'
                 f'{C[kind]}swimlaneFillColor=#FFFFFF;opacity=100;')
        self.cells.append(f'<mxCell id="{cid}" value="{escape(label)}" style="{style}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def text(self, label, x, y, w, h, extra=''):
        cid = self._id()
        y += self.oy
        style = f'text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;{FONT}fontColor=#55625A;{extra}'
        self.cells.append(f'<mxCell id="{cid}" value="{escape(label)}" style="{style}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cid

    def edge(self, src, dst, label='', extra='', color='#55625A', dashed=False):
        cid = self._id()
        style = (f'edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;{FONT}fontSize=10;'
                 f'strokeColor={color};fontColor={color};labelBackgroundColor=#FFFFFF;strokeWidth=1.4;'
                 f'{"dashed=1;" if dashed else ""}{extra}')
        self.cells.append(f'<mxCell id="{cid}" value="{escape(label)}" style="{style}" edge="1" parent="1" '
                          f'source="{src}" target="{dst}"><mxGeometry relative="1" as="geometry"/></mxCell>')
        return cid

    def write(self, filename):
        body = ''.join(self.cells)
        xml = (f'<mxfile host="SyringeTwin"><diagram name="{escape(self.name)}" id="{filename}">'
               f'<mxGraphModel dx="{self.width}" dy="{self.height}" grid="1" gridSize="10" guides="1" '
               f'page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" background="#FFFFFF">'
               f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{body}</root></mxGraphModel></diagram></mxfile>')
        (OUT / f'{filename}.drawio').write_text(xml, encoding='utf-8')


def title(d, text, sub):
    d.text(f'<b style="font-size:20px;color:#1F3A1A">{text}</b><br><span style="font-size:12px">{sub}</span>',
           40, 20, 1400, 56)


# 1. System architecture -----------------------------------------------------
def architecture():
    d = Diagram('System architecture', 1600, 1060)
    title(d, '1 · System architecture', 'ISA-95 layers of the SyringeTwin digital twin. Only the twin owns simulated time; in PLC mode the PLC owns run, E-stop and F201 decisions.')
    down = 'exitX=0.5;exitY=0;entryX=0.5;entryY=1;'
    l3 = d.lane('Level 3 · MES / digital twin (Python, twin/)', 40, 100, 1520, 330, 'twin')
    d.box('<b>Plant model</b><br>plant.py<br>motion · refills · wear · quality sampling', 30, 45, 260, 85, 'twin', parent=l3)
    d.box('<b>Sequence control</b><br>control.py<br>SFC steps · transfer interlocks · inspection', 320, 45, 270, 85, 'twin', parent=l3)
    d.box('<b>Fixed-step engine</b><br>engine.py · dt 0.1 s · seed 7 · 1×–50×', 620, 45, 260, 85, 'twin', parent=l3)
    d.box('<b>KPI + condition monitoring</b><br>kpi.py · throughput · OEE (run + rolling 10 min)<br>W202 · cycles to overload', 910, 45, 300, 85, 'twin', parent=l3)
    d.box('<b>What-if sandbox</b><br>whatif.py<br>copy → change → run → compare → recommend', 1240, 45, 250, 85, 'ops', parent=l3)
    bridge = d.box('<b>PLC bridge</b><br>plc_bridge.py · Modbus TCP client<br>20 ms exchange · watchdog F002', 30, 175, 230, 95, 'plc', parent=l3)
    d.box('<b>Historian</b><br>SQLite per run · parts · events<br>alarms · commands · KPI samples', 290, 175, 230, 95, 'grey', parent=l3)
    d.box('<b>Commands + audit</b><br>commands.py<br>who · what · when for every action', 550, 175, 220, 95, 'grey', parent=l3)
    api = d.box('<b>Service + REST API</b><br>service.py · api.py · FastAPI :8000<br>/api/live · /commands · /parts · /whatif', 800, 175, 300, 95, 'twin', parent=l3)
    opcua = d.box('<b>OPC UA server</b><br>opc.tcp://127.0.0.1:4840<br>read-only Line1.* namespace', 1130, 175, 250, 95, 'twin', parent=l3)

    l2 = d.lane('Level 2 · Supervision and operation', 40, 470, 1520, 160, 'ops')
    d.box('<b>Streamlit dashboard</b><br>fallback HMI · :8501 · via REST API', 230, 45, 220, 90, 'grey', parent=l2)
    d.box('<b>Hosted browser copy</b><br>same Python model in Pyodide<br>independent, no laptop needed', 480, 45, 250, 90, 'grey', parent=l2)
    dash = d.box('<b>Web dashboard</b> (HMI + MES views)<br>live cell · performance · alarms &amp; audit<br>traceability · maintenance · decision support', 760, 45, 380, 90, 'ops', parent=l2)
    uaexpert = d.box('<b>UaExpert</b><br>OPC UA client · browse / trend', 1145, 45, 220, 90, 'grey', parent=l2)

    l1 = d.lane('Level 1 · Control (IEC 61131-3)', 40, 670, 1520, 165, 'plc')
    openplc = d.box('<b>OpenPLC Runtime</b> · syringetwin.st · task 20 ms<br>P1 master control: run seal-in, E-stop latch, tower light<br>P5 S2 force check · F201 latch · INSERT permissive<br>P8 reset rules · F002 watchdog · P9 counters', 30, 40, 520, 105, 'plc', parent=l1)
    d.box('<b>Fallback path</b><br>GX Works3 + GT Designer3<br>same labels · standalone simulators', 580, 40, 280, 105, 'grey', parent=l1)

    l0 = d.lane('Level 0 · Simulated process (modelled by plant.py)', 40, 875, 1520, 120, 'grey')
    d.box('<b>Syringe assembly cell</b>: IN → B1 → S1 print/cure → B2 → <b>S2 press/insert (bottleneck)</b> → B3 → S3 cap/mark → B4 → S4 inspection → OUT packing · 10 pallets · 2 s transfers', 30, 38, 1100, 62, 'white', parent=l0)

    d.edge(dash, api, 'HTTP JSON · 2 Hz poll + commands', color='#9A7A2C', extra=down)
    d.edge(uaexpert, opcua, 'OPC UA', color='#46733D', extra=down)
    d.edge(bridge, openplc, 'Modbus TCP :502 · %MW0–27 → PLC · %QX / %QW → twin', color='#3F6B93',
           extra='exitX=0.5;exitY=1;entryX=0.221;entryY=0;')
    d.write('01_system_architecture')


# 2. Factory / process flow ----------------------------------------------------
def process_flow():
    d = Diagram('Process flow', 1700, 760)
    title(d, '2 · Factory and material flow', 'Pallet loop with FIFO buffers (capacity 2). Times are simulation seconds; each station cycle = steps + one 2 s pallet transfer.')
    y = 260
    stations = [('IN', 'Material input', 'PICK 1.5 · PLACE 1.0<br>WRITE_ID 0.5', '3.0 + 2 = 5 s', 'white'),
                ('S1', 'Print + UV cure', 'CLAMP 0.5 · PRINT 2.0<br>CURE 3.0 · UNCLAMP 0.5', '6.0 + 2 = 8 s', 'white'),
                ('S2', 'Press + insert', 'PRESS 2.0 · INSERT 3.0<br>RETRACT 1.5 · RELEASE 0.5<br>HANDLING 1.0', '8.0 + 2 = <b>10 s</b><br><b>bottleneck · 360/h</b>', 'warn'),
                ('S3', 'Cap + laser mark', 'CAP_PRESS 1.5 · LASER 2.5<br>VERIFY 1.0', '5.0 + 2 = 7 s', 'white'),
                ('S4', 'Inspection', 'VISION 1.0 · LEAK 3.0<br>DECIDE 0.5 · DIVERT 0.5', '5.0 + 2 = 7 s', 'twin')]
    ids, xs = [], [40 + i * 290 for i in range(5)]
    for i, (name, fn, steps, ct, kind) in enumerate(stations):
        ids.append(d.box(f'<b>{name} · {fn}</b><br><span style="font-size:10px">{steps}</span><br>{ct}', xs[i], y, 190, 120, kind))
        if i < 4:
            ids.append(d.box(f'<b>B{i + 1}</b><br>FIFO · 2', xs[i] + 210, y + 35, 60, 50, 'grey'))
    x = xs[-1] + 190
    out = d.box('<b>OUT · Packing</b><br>UNLOAD 1.0<br>box of 10 good units', x + 60, y - 70, 190, 90, 'twin')
    rej = d.box('<b>Reject bin</b><br>R1 print · R2 force · R3 leak<br>R4 cap · R5 mark grade D', x + 60, y + 90, 190, 90, 'fault')
    for a, b in zip(ids, ids[1:]):
        d.edge(a, b, '2 s')
    d.edge(ids[-1], out, 'PASS')
    d.edge(ids[-1], rej, 'FAIL · divert')
    ret_w = x + 250 - 40
    ret = d.box('<b>Empty pallet return</b> · 10 s · 10 unique pallets (WIP ≤ 10)', 40, 520, ret_w, 40, 'grey')
    d.edge(out, ret, 'empty pallet', dashed=True, extra='exitX=1;exitY=0.5;entryX=1;entryY=0.5;')
    d.edge(rej, ret, '', dashed=True, extra=f'exitX=0.5;exitY=1;entryX={(x + 155 - 40) / ret_w:.4f};entryY=0;')
    d.edge(ret, ids[0], 'empty pallet to IN', dashed=True, extra=f'exitX={95 / ret_w:.4f};exitY=0;entryX=0.5;entryY=1;')
    bins = [('Barrel hopper 300<br>W001 &lt; 30', 0), ('Plunger 150 · Stopper 150<br>W210 / W211 &lt; 15', 4), ('Cap bin 200<br>W310 &lt; 20', 6)]
    for label, target in bins:
        b = d.box(f'<b>Material</b><br>{label}<br>auto-refill 30 s', xs[target // 2], 110, 190, 70, 'ops')
        d.edge(b, ids[target], 'consumed at step start', color='#9A7A2C')
    d.text('<b>Measurements generated</b>: S1 print offset (R1) · S2 press force = 120 + 40·wear + N(0,4) N (R2 outside 105–140 N; F201 above 160 N) · '
           'S3 cap OK / mark grade (R4, R5) · S4 leak rate, higher if force was out of window (R3 above 5 Pa/s).', 40, 600, 1480, 60)
    d.text('<b>States</b> (PackML-lite): STOPPED · STARVED · RUNNING · BLOCKED · FAULT · MAINT. A station is BLOCKED when its downstream buffer is full and STARVED when it has no pallet or no material.', 40, 660, 1480, 50)
    d.write('02_process_flow')


# 3. Data architecture --------------------------------------------------------
def data_architecture():
    d = Diagram('Data architecture', 1600, 760)
    title(d, '3 · Data architecture', 'Where every value comes from, where it goes, and in what format. One source of truth: the engine state.')
    x0, width, col, gap = 100, 1420, 220, 20
    xs = [x0 + i * (col + gap) for i in range(6)]
    at = lambda i: f'{(xs[i] + col / 2 - x0) / width:.4f}'
    state = d.box('<b>Engine state</b> (model.State) · the only place time advances (fixed dt 0.1 s)<br>stations · buffers · pallets · parts · bins · alarms · commands · events · random generator per station',
                  x0, 100, width, 70, 'twin')
    r2, r3 = 250, 440
    payload = d.box('<b>Live payload</b> (0.5 s)<br>snapshot: states, counts,<br>bins, alarms<br>kpi: throughput, OEE, oee_win<br>meta: transfers, PLC status', xs[0], r2, col, 120, 'twin')
    dash = d.box('<b>Dashboards</b><br>GET /api/live (2 Hz)<br>GET /api/parts/{serial}<br>/alarms · /events', xs[0], r3, col, 100, 'ops')
    cmd = d.box('<b>Operator command</b><br>POST /api/commands<br>{cmd, args, user}<br>validated → applied →<br>audited', xs[1], r2, col, 120, 'ops')
    hist = d.box('<b>Historian · SQLite</b><br>one database per run<br>parts · part_events · alarms<br>commands · kpi_samples<br>state_log', xs[2], r2, col, 120, 'grey')
    exports = d.box('<b>Exports</b><br>part trace JSON · audit CSV<br>trends CSV · what-if JSON<br>validation matrix', xs[2], r3, col, 100, 'grey')
    whatif = d.box('<b>What-if</b><br>POST /api/whatif<br>deep copy under lock →<br>headless options →<br>result JSON', xs[3], r2, col, 120, 'ops')
    opc = d.box('<b>OPC UA address space</b><br>ns=2;s=Line1.…<br>Stations.&lt;St&gt;.State<br>S2.Force · KPI.OEE<br>PLC.F201', xs[4], r2, col, 120, 'twin')
    ua = d.box('<b>UaExpert</b><br>browse · subscribe · trend', xs[4], r3, col, 100, 'grey')
    regs = d.box('<b>Modbus register map</b><br>twin → PLC %MW0–27<br>commands, E-stop OK, tool OK,<br>force×10, sequence numbers<br>PLC → twin %QX0.0–1.3 · %QW0–6', xs[5], r2, col, 120, 'plc')
    plc = d.box('<b>OpenPLC Runtime</b><br>syringetwin.st · 20 ms scan', xs[5], r3, col, 100, 'plc')
    down = lambda i: f'exitX={at(i)};exitY=1;entryX=0.5;entryY=0;'
    d.edge(state, payload, 'engine.payload()', extra=down(0))
    d.edge(payload, dash, 'JSON / HTTP', color='#9A7A2C')
    d.edge(cmd, state, 'execute or send to PLC', color='#9A7A2C', extra=f'exitX=0.5;exitY=0;entryX={at(1)};entryY=1;')
    d.edge(state, hist, 'sample · 2 Hz', extra=down(2))
    d.edge(hist, exports, '', dashed=True)
    d.edge(state, whatif, 'deepcopy', color='#9A7A2C', dashed=True, extra=down(3))
    d.edge(state, opc, 'publish · 0.5 s', extra=down(4))
    d.edge(opc, ua, 'OPC UA', color='#46733D')
    d.edge(state, regs, 'plc_bridge.outputs()', color='#3F6B93', extra=down(5))
    d.edge(regs, plc, 'write / read · 20 ms', color='#3F6B93')
    d.edge(plc, state, 'run · F001 · F201 · F002 · verdict', color='#3F6B93',
           extra='exitX=1;exitY=0.5;entryX=1;entryY=0.5;')
    d.text('<b>Tag dictionary</b>: docs/plc/tag_dictionary.csv lists every signal once: twin field, OpenPLC address, Modbus register, GX Works3 device, OPC UA node and HMI object.', x0, 580, width, 30)
    d.text('<b>Rules</b>: dashboards change state only through audited commands · what-if never touches the live state · undefined values are null and shown as “—” · every figure in the report comes from a saved run in docs/evidence.', x0, 615, width, 40)
    d.write('03_data_architecture')


# 4. F201 cause and effect -------------------------------------------------------
def f201_chain():
    d = Diagram('F201 cause and effect', 1600, 900)
    title(d, '4 · F201 press overload: cause → effect → recovery', 'The required machine fault has a physical cause, an early warning, a local effect that propagates through material flow, and an audited recovery.')
    d.oy = 90
    wear = d.box('<b>Tool wear rises</b><br>+0.004 per press<br>(demo profile +0.010)', 40, 110, 210, 80, 'warn')
    force = d.box('<b>Press force rises</b><br>F = 120 + 40·wear + N(0, 4) N', 290, 110, 230, 80, 'warn')
    w202 = d.box('<b>W202 early warning</b> (amber)<br>5-press mean &gt; 135 N or<br>trend predicts &lt; N cycles to 160 N', 560, 30, 270, 80, 'warn')
    quality = d.box('<b>Quality degrades</b><br>force outside 105–140 N → R2<br>damaged seal → leak &gt; 5 Pa/s → R3', 560, 160, 270, 80, 'fault')
    decide = d.box('<b>Decision support</b><br>what-if: keep running vs change tool now<br>vs condition-based changes', 880, 30, 280, 80, 'ops')
    trip = d.box('<b>Force &gt; 160 N</b><br>PLC P5-R1 sets F201<br>(or operator injection, tagged)', 290, 300, 230, 80, 'plc')
    fault = d.box('<b>S2 → FAULT</b><br>holds its pallet · outputs off<br>line keeps running (local fault)', 560, 300, 270, 80, 'fault')
    up = d.box('<b>Upstream blocks</b><br>B2 fills → S1 BLOCKED → B1 → IN BLOCKED', 880, 250, 300, 70, 'fault')
    down = d.box('<b>Downstream starves</b><br>S3, S4, OUT STARVED', 880, 350, 300, 70, 'fault')
    kpis = d.box('<b>KPIs react</b><br>throughput → 0 · availability ↓<br>rolling OEE ↓ · downtime clock runs', 1220, 300, 260, 80, 'fault')
    alarm = d.box('<b>Alarm</b><br>red flashing lamp + horn (PLC P1-R4)<br>dashboard banner · alarm log', 1220, 450, 260, 80, 'fault')
    repair = d.box('<b>Repair S2</b><br>MTTR 90 s · wear → 0<br>I_S2_TOOL_OK 0 → 1', 1220, 600, 260, 80, 'ops')
    reset = d.box('<b>Reset</b><br>PLC P8-R2 clears F201 only after repair<br>(early reset refused)', 880, 600, 300, 80, 'plc')
    resume = d.box('<b>S2 resumes at RETRACT</b><br>blocked/starved stations recover<br>throughput and rolling OEE recover', 560, 600, 270, 80, 'twin')
    reject = d.box('<b>Affected unit</b><br>keeps its force trace → rejected R2 at S4<br>full history in traceability', 230, 600, 290, 80, 'twin')
    d.edge(wear, force)
    d.edge(force, w202, 'monitored')
    d.edge(force, quality, '> 140 N')
    d.edge(w202, decide, 'prompts')
    d.edge(force, trip, '> 160 N', color='#B0563F')
    d.edge(trip, fault, '', color='#B0563F')
    d.edge(fault, up, '', color='#B0563F')
    d.edge(fault, down, '', color='#B0563F')
    d.edge(up, kpis, '', color='#B0563F')
    d.edge(down, kpis, '', color='#B0563F')
    d.edge(kpis, alarm, '', color='#B0563F')
    d.edge(alarm, repair, 'operator')
    d.edge(repair, reset, 'tool OK')
    d.edge(reset, resume)
    d.edge(resume, reject)
    d.edge(decide, wear, 'tool change resets wear (prevents the chain)', color='#9A7A2C', dashed=True,
           extra='exitX=0.5;exitY=0;entryX=0.5;entryY=0;')
    d.text('<b>Measured</b> (validation matrix, demo profile, seed 7): W202 at ~409 sim-s, first R2 at ~453 sim-s, F201 at 869 sim-s (force 161.9 N); S1 BLOCKED 4.1 s and S3 STARVED 5.0 s after the trip; repair 90.0 s; affected part rejected R2 + R3.',
           40, 740, 1440, 50)
    d.write('04_f201_cause_effect')


# 5. What-if decision loop --------------------------------------------------------
def whatif_loop():
    d = Diagram('What-if decision loop', 1500, 820)
    title(d, '5 · What-if decision loop', 'The twin as a decision tool: test a decision on a copy before applying it to the line.')
    live = d.box('<b>1 · Live twin</b><br>state at time t<br>(wear, force, WIP, alarms, RNG)', 60, 150, 230, 90, 'twin')
    copy = d.box('<b>2 · Virtual copy</b><br>deepcopy under the engine lock<br>same random-number state', 360, 150, 240, 90, 'twin')
    change = d.box('<b>3 · Change one decision</b><br>A: keep running · tool change now ·<br>condition-based changes<br>B: one process step duration', 670, 150, 270, 90, 'ops')
    run = d.box('<b>4 · Accelerated run</b><br>headless, no pacing: 1 sim-hour &lt; 1 s<br>same automatic operator in every option<br>1 or 5 random seeds', 1010, 150, 290, 100, 'ops')
    compare = d.box('<b>5 · Compare KPIs</b><br>good units · throughput · rejects · Q · OEE<br>F201 count · downtime · lead time<br>design vs simulated bottleneck', 1010, 360, 290, 100, 'ops')
    rec = d.box('<b>6 · Recommend</b><br>best good output, only if ≥ 2 % gain<br>and better in ≥ 4 of 5 seeds;<br>otherwise “keep current” with the reason', 670, 360, 270, 100, 'ops')
    act = d.box('<b>7 · Operator acts</b><br>e.g. Schedule tool change<br>command validated and audited', 360, 360, 240, 100, 'grey')
    d.edge(live, copy)
    d.edge(copy, change)
    d.edge(change, run)
    d.edge(run, compare)
    d.edge(compare, rec)
    d.edge(rec, act)
    d.edge(act, live, 'applied to the live line')
    d.box('<b>Guarantee</b>: the live twin is never modified by an analysis (tested: state fingerprint identical before and after).', 60, 520, 540, 60, 'grey')
    d.text('<b>Measured results</b> (validation matrix, 20 sim-min of default production, 1 sim-hour horizon):<br>'
           'A · keep running 217 /h, change tool now 234 /h, <b>condition-based 337 /h</b> · F201 2 → 0 · better in 5/5 seeds<br>'
           'B · S1 cure 3 → 2 s: +0 % (not the bottleneck) · S2 insert 3 → 0.5 s: +27.7 %, design bottleneck moves S2 → S1<br>'
           'Forecast check: “keep running” predicted the next live F201 at 229.2 sim-s; the live line tripped at 229.2 sim-s.',
           660, 510, 760, 110)
    d.write('05_whatif_loop')


if __name__ == '__main__':
    for build in (architecture, process_flow, data_architecture, f201_chain, whatif_loop):
        build()
    print('Wrote', ', '.join(sorted(p.name for p in OUT.glob('*.drawio'))))
