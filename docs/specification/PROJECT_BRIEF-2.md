# SyringeTwin — Digital Twin of a Smart Syringe Assembly Cell
Group 07 · Digital Twin of a Smart Factory · 3 days · 4–5 members

> **Single source of truth.** If code, a person or an AI disagrees with this file, this file wins.
> Section §8 (data contracts) and §6.3 (tag map) are **frozen at CP0**. Only the Lead (R1) may change them, and every change gets a line in §16 Changelog.

**Pack contents**

| File | Purpose |
|---|---|
| `PROJECT_BRIEF.md` | What we build: spec, contracts, KPIs, demo |
| `skills.md` | How to build it: conventions, domain knowledge, AI prompt templates |
| `roles.md` | Who builds what, plus the operating charter for any AI assistant |
| `ACTION_PLAN.md` | When: hour-by-hour plan, checkpoints, fallbacks |

**AI load order:** brief → skills → roles → action plan. Then give the AI its role and current task.

---

## 1. Concept
A pallet-based assembly cell makes 3-part disposable syringes (barrel, plunger with rubber stopper, tip cap). The twin is built from four parts:

1. A **plant physics model** (pallets, buffers, parts, sensors, wear)
2. A **PLC-faithful control layer** (the same tag map and ladder/SFC logic a real PLC would run)
3. An **MES layer** (KPIs, traceability, predictive maintenance, what-if)
4. A **live HMI dashboard**

The parts talk to each other over MQTT. Medical-device manufacturing justifies two features: 100 % inspection, and per-unit serial traceability.

## 2. What makes it unique
| # | Feature | Why it scores |
|---|---|---|
| U1 | **PLC-faithful control.** The sim is driven by the same I/O tags and the same ladder/SFC logic documented in `docs/plc/` | Shows automation engineering, not just a Python animation |
| U2 | **Per-unit traceability.** Click any serial to see its full timeline and measurements | Medical-device realism (UDI, ISO 13485) |
| U3 | **Predictive maintenance on S2.** Tool wear → force drift → rejects → overload fault, with predicted cycles-to-fault | The required fault has a physical cause and an early warning |
| U4 | **What-if sandbox.** Fork the live state, fast-forward 1 h with changed parameters, compare KPIs | Uses the twin as a decision tool, which is the actual point of a twin |
| U5 | **Self-validation.** Live conservation and Little's Law checks | Proves the model is correct |
| U6 | **Audit trail.** Every operator command is logged (who, what, when) | 21 CFR Part 11 flavour at almost no cost |

## 3. Process flow and layout
Required flow, mapped: **Material Input → Station 1 → Station 2 → (Station 3) → Inspection → Finished Product**

```
   ┌──────────────── pallet return conveyor (10 s) ─────────────────┐
   ▼                                                                 │
 [IN] →B1→ [S1 PRINT+CURE] →B2→ [S2 PRESS+INSERT] →B3→ [S3 CAP+MARK] →B4→ [S4 INSPECT] → [OUT]
   ▲                ▲                 ▲        ▲               ▲                     ├ PASS → pack (box = 10)
 barrel hopper   ink / UV        plunger bin  stopper bin     cap bin                └ FAIL → reject bin
```
- Each station slot holds 1 pallet. B1–B4 are FIFO buffers with capacity 2.
- A transfer between any two slots takes **2 s**. There are **10 pallets**, which caps WIP at 10.
- After OUT, the empty pallet returns to IN.
- **Bottleneck = S2.** Its 8 s process plus a 2 s pallet index gives a 10 s design cycle, so the **design rate is 360 syringes/h**. 450/h (3600/8) is the process-only ideal.
- **Transfer rules (DECISIONS D2):** release frees the source slot; the pallet is in transit for 2 s; the destination is reserved while it travels; buffers auto-feed an empty, unreserved station.

## 4. Station specification
Durations are sim-seconds. Every value lives in `config/line.yaml`, never hard-coded.

| Station | Function | Sequence (SFC steps, s) | Cycle | Quality data generated → reject code | Faults / warnings | Consumables |
|---|---|---|---|---|---|---|
| **IN** | Load barrel onto empty pallet, assign serial | WAIT_PALLET → PICK 1.5 → PLACE 1.0 → WRITE_ID 0.5 → RELEASE | 3.0 | Serial `SYR-B07-000001…` | W001 hopper < 30; empty → STARVED | Hopper 300 barrels |
| **S1** | Pad-print graduations, UV cure | WAIT → CLAMP 0.5 → PRINT 2.0 → CURE 3.0 → UNCLAMP 0.5 → RELEASE | 6.0 | `print_offset_mm` ~ N(0, 0.05); \|x\| > 0.15 → **R1** | F101 UV lamp fail (Should) | Ink (not modelled) |
| **S2** | Press stopper onto plunger, insert into barrel | WAIT → PRESS 2.0 (sample force) → INSERT 3.0 → RETRACT 1.5 → RELEASE 0.5 (+1.0 handling) | 8.0 | `force_N` = 120 + 40·wear + N(0, 4); outside 105–140 → **R2** | **F201 press overload: force > 160 N (the required fault)**; W202 tool wear; W210/W211 bins < 15 | Plunger 150, stopper 150 |
| **S3** | Fit tip cap, laser-mark UDI DataMatrix | WAIT → CAP_PRESS 1.5 → LASER 2.5 → VERIFY 1.0 → RELEASE | 5.0 | `cap_ok` (p = 0.995) → **R4**; `mark_grade` A–D (P = .80/.15/.04/.01), D → **R5** | W310 cap bin < 20 | Caps 200 |
| **S4** | Inspection: vision and leak (pressure-decay) test, reject diverter | WAIT → VISION 1.0 → LEAK 3.0 → DECIDE 0.5 → DIVERT/PASS 0.5 → RELEASE | 5.0 | `leak_Pa_s` ~ N(2, 0.5), plus N(6, 2) if S2 force was out of window; > 5 → **R3**. Vision re-checks R1, R4, R5 | F401 transfer jam (Should) | — |
| **OUT** | Unload: good parts to box, rejects to bin | UNLOAD 1.0 | — | Box complete every 10 good | — | — |

**Wear model (S2).**
- `wear` += 0.004 per cycle, and `initial_wear` is set in config (use 0.3 for the demo).
- Rejects (R2) start near wear 0.5, and F201 comes near wear 1.0. Wear increments when PRESS completes, and the trip cycle counts.
- From `initial_wear 0.3` at a 10 s cycle and 10× speed: mean rejects start after about 50 cycles (≈ 50 s wall time) and the mean trip comes after about 175 cycles (≈ 2.9 min). Noise shifts both, so **measure them, don't promise them.**
- **Stock is consumed** at these points: barrel at PICK, plunger and stopper at PRESS start, cap at CAP_PRESS start.
- **Repair:** unplanned repair after F201 takes MTTR 90 s; a planned tool change (MAINT) takes 20 s. Both reset wear to 0.

**Physical correlation.** Wear raises force. Out-of-window force raises the leak rate, and leak failures rise before the fault. The evaluator sees cause → effect.

**Material handling.** When a bin hits its low level (W2xx/W310), an auto-refill arrives 30 s later. A dashboard "Refill" button does the same thing. An empty bin makes the station STARVED (material).

## 5. Machine state model (PackML-lite)
| State | Meaning | Shown as (spec wording) | Colour |
|---|---|---|---|
| STOPPED | Line not running (Stop or E-stop) | Idle | dark grey |
| STARVED | Running, but no pallet or no material | **Idle** (reason: starved) | light grey |
| RUNNING | Executing its sequence | **Running** | green |
| BLOCKED | Done, but the next slot or buffer is full | **Idle** (reason: blocked) | amber |
| FAULT | Latched alarm; needs repair and reset | **Fault** | red |
| MAINT | Planned tool change | Maintenance | blue |

**Tower light rules**
- Red flashes plus the horn: any FAULT.
- Amber: any warning or any station BLOCKED.
- Green: line running with no faults.

## 6. PLC control layer
### 6.1 Split by ISA-95 level
- **PLC (L1/L2):** sequences, interlocks, E-stop, alarm latching, counters, timers. Only these get PLC diagrams.
- **MES (L3), not PLC:** KPIs, genealogy, prediction, what-if. These are Python.

### 6.2 Where PLC diagrams are required
| ID | Diagram | Type | Content | Tier |
|---|---|---|---|---|
| P1 | Master control | LD | E-stop chain, Start/Stop seal-in, Auto/Manual, Reset, tower light, horn | MVP |
| P2 | Transfer interlock (one rung template per slot) | LD | Release slot n only if done, next buffer not full, line running, no station fault | MVP |
| P3 | Infeed sequence | SFC → LD | §4 IN steps, serial write | MVP |
| P4 | S1 sequence | SFC → LD | Clamp, print, cure timer (TON) | MVP |
| P5 | S2 sequence and force monitoring | SFC → LD with compare blocks | Force window check, F201 latch | MVP |
| P6 | S3 sequence | SFC → LD | Cap press, laser, verify | MVP |
| P7 | S4 sequence and reject diverter | SFC → LD | Leak timer, pass/fail decision, diverter pulse | MVP |
| P8 | Alarm handling | LD (S/R coils) | Latch per alarm, reset needs the condition cleared, any-fault/any-warn summaries | MVP |
| P9 | Counters | LD (CTU) | C_IN, C_GOOD, C_REJECT, C_BOX (PV = 10, auto-reset) | MVP |
| P10 | Jam watchdog | LD (TON) | Transfer > 5 s → F401 | Should |
| P11 | Material low/empty | LD (compare) | W001/W210/W211/W310, empty → starved | Should |

**Notation.** Interlocks use Ladder (LD). Sequences are designed as SFC/Grafcet first, then implemented in LD with a step register (or IEC ST `CASE`). The ASCII format is defined in `skills.md` §A1.

### 6.3 I/O and tag map (frozen at CP0)
Addresses follow OpenPLC conventions. The source of truth is `twin/tags.py`, mirrored in `docs/plc/io_list.csv`.

| Group | Inputs | Outputs |
|---|---|---|
| Panel | `I_ESTOP_OK` %IX0.0 (NC chain, 1 = healthy) · `I_START_PB` %IX0.1 · `I_STOP_PB` %IX0.2 (NC, 1 = not pressed) · `I_RESET_PB` %IX0.3 · `I_AUTO` %IX0.4 | `Q_LAMP_GREEN` %QX0.0 · `Q_LAMP_AMBER` %QX0.1 · `Q_LAMP_RED` %QX0.2 · `Q_HORN` %QX0.3 |
| IN | `I_IN_POS` %IX1.0 · `I_IN_HOPPER_OK` %IX1.1 · `I_IN_PICK_DONE` %IX1.2 | `Q_IN_PICK` %QX1.0 · `Q_IN_RELEASE` %QX1.1 |
| S1 | `I_S1_POS` %IX2.0 · `I_S1_CLAMPED` %IX2.1 · `I_S1_PRINT_DONE` %IX2.2 · `I_S1_UV_OK` %IX2.3 | `Q_S1_CLAMP` %QX2.0 · `Q_S1_PRINT` %QX2.1 · `Q_S1_UV` %QX2.2 · `Q_S1_RELEASE` %QX2.3 |
| S2 | `I_S2_POS` %IX3.0 · `I_S2_PRESS_UP` %IX3.1 · `I_S2_PRESS_DN` %IX3.2 · `I_S2_INSERT_DONE` %IX3.3 · `I_S2_PLUNGER_OK` %IX3.4 · `I_S2_STOPPER_OK` %IX3.5 · `I_S2_TOOL_OK` %IX3.6 (repair complete) · `AI_S2_FORCE` %IW0 (N × 10) | `Q_S2_PRESS` %QX3.0 · `Q_S2_INSERT` %QX3.1 · `Q_S2_RELEASE` %QX3.2 |
| S3 | `I_S3_POS` %IX4.0 · `I_S3_CAP_OK` %IX4.1 · `I_S3_CAP_SEATED` %IX4.2 · `I_S3_MARK_DONE` %IX4.3 | `Q_S3_CAP_PRESS` %QX4.0 · `Q_S3_LASER` %QX4.1 · `Q_S3_RELEASE` %QX4.2 |
| S4 | `I_S4_POS` %IX5.0 · `I_S4_VISION_DONE` %IX5.1 · `I_S4_VISION_PASS` %IX5.2 · `AI_S4_LEAK` %IW1 (Pa/s × 10) | `Q_S4_LEAK_VALVE` %QX5.0 · `Q_S4_REJECT` %QX5.1 · `Q_S4_RELEASE` %QX5.2 |
| Flow / OUT | `I_B1_FULL`…`I_B4_FULL` %IX6.0–6.3 (= occupied + reserved ≥ capacity, computed by the plant) · `I_OUT_POS` %IX6.4 · `I_OUT_UNLOADED` %IX6.5 *(v1.1)* | `Q_OUT_UNLOAD` %QX6.0 *(v1.1)* |
| Internal (BOOL/INT, no address) | `M_SYS_RUN`, `M_ANY_FAULT`, `M_ANY_WARN`, `M_<St>_STEP` (INT), `M_<St>_DONE`, `F_<St>` (station fault), alarm bits `F001 F101 F201 F401`, warning bits `W001 W202 W210 W211 W310`, counters `C_IN C_GOOD C_REJECT C_BOX`, timers `T_<St>_<STEP>` | |

**Rule.** No tag may be used unless it exists in `tags.py`. A new tag is proposed as `NEW_TAG` and approved by R1.

### 6.4 Implementation path
- **MVP.** `twin/control.py` runs a **100 ms scan** each cycle: read the plant inputs, evaluate P1–P11 in order, then write the outputs back to the plant. Every Python block carries a comment such as `# P5-R3` that links it to its diagram rung.
- **Docs.** R5 redraws the ASCII ladder in **OpenPLC Editor** (free) and exports the screenshots to `docs/plc/`.
- **Stretch (software-in-the-loop).** Run the same logic as IEC ST in **OpenPLC Runtime**, with the sim exchanging I/O over Modbus TCP (`pymodbus`). The real soft-PLC then replaces `control.py`, with no changes needed in the plant model or dashboard.

## 7. Software architecture
```
 engine.py (clock · speed · seed · what-if fork)
   └─ every tick: plant.py (physics, sensors)  ⇄  control.py (PLC scan, tags.py)
         │ snapshot + events
   bridge.py ──MQTT──► Mosquitto :1883 / ws :9001 ──► dashboard/ (HTML + JS)
         │                                                  │
   kpi.py (KPIs, health, validation) → historian.py (SQLite)  ◄── commands (MQTT sf/line1/cmd)
   api.py (FastAPI: genealogy · alarms · what-if) — same process, reads SQLite
```

**Stack**
- **Backend:** Python 3.11, `paho-mqtt` 2.x, `fastapi` + `uvicorn`, `numpy`, `pyyaml`, `pytest`, SQLite (stdlib).
- **Frontend:** plain HTML/JS with `mqtt.js`, `Chart.js` and inline SVG. No build step.
- **Broker:** Mosquitto, with a WebSocket listener on 9001.

**Process model.** One command, `python -m twin`, starts the engine thread, the MQTT bridge and the FastAPI server on :8000, which also serves `dashboard/`.

**Repo layout**
```
smart-factory-twin/
  PROJECT_BRIEF.md  skills.md  roles.md  ACTION_PLAN.md  README.md (run steps)
  config/line.yaml        mosquitto.conf
  twin/ __main__.py engine.py plant.py control.py tags.py bridge.py kpi.py historian.py api.py
  dashboard/ index.html app.js style.css
  docs/plc/ io_list.csv P1..P11.md (ASCII + SFC) *.png (OpenPLC screenshots)
  tests/ test_conservation.py test_little.py test_control.py test_determinism.py
  scenarios/demo.yaml
```

**`mosquitto.conf`**
```
listener 1883
listener 9001
protocol websockets
allow_anonymous true
```

**`config/line.yaml` (shape; R2 fills in the values from §4)**
```yaml
seed: 7
dt: 0.1                # sim step, s
scan_ms: 100           # PLC scan
pallets: 10
transfer_s: 2.0
return_s: 10.0
buffers: {B1: 2, B2: 2, B3: 2, B4: 2}
stations:
  S2: {steps: {PRESS: 2.0, INSERT: 3.0, RETRACT: 1.5, RELEASE: 0.5, HANDLING: 1.0},
       force: {base: 120, wear_gain: 40, sigma: 4, win: [105, 140], trip: 160},
       wear_per_cycle: 0.004, initial_wear: 0.3, mttr_s: 90, tool_change_s: 20}
bins: {hopper: 300, plunger: 150, stopper: 150, cap: 200}
refill_delay_s: 30
policy: {predictive_tool_change: false}
```

## 8. Data contracts (frozen at CP0)
### 8.1 MQTT (QoS 0, prefix `sf/line1`)
| Topic | Direction | Rate | Payload |
|---|---|---|---|
| `sf/line1/snapshot` | twin → HMI (retained) | 2 Hz wall-clock | §8.2 |
| `sf/line1/kpi` | twin → HMI (retained) | 1 Hz | §8.3 |
| `sf/line1/event` | twin → HMI | on event | `{t, type: part\|inspection\|alarm\|box\|cmd, ...}` |
| `sf/line1/cmd` | HMI → twin | on click | §8.4 |

`t` is sim time in seconds (float). `wall` is ISO-8601 with +05:30. Snapshots are full state, never deltas.

### 8.2 Snapshot
```json
{"t":1234.5,"wall":"2026-10-08T10:15:02+05:30","run":true,"speed":10,"lamp":"GREEN",
 "stations":{"S2":{"state":"RUNNING","reason":null,"step":"PRESS","part":"SYR-B07-000123",
   "cycles":152,"last_ct":8.1,"down_s":0.0,"wear":0.61,"force":144.2}},
 "buffers":{"B1":["SYR-B07-000130"],"B2":[],"B3":[],"B4":[]},
 "bins":{"hopper":212,"plunger":88,"stopper":91,"cap":160},
 "counts":{"in":162,"good":148,"reject":5,"wip":9,"boxes":14},
 "alarms":[{"code":"W202","sev":"WARN","since":1200.0,"text":"S2 tool wear high"}]}
```
The `stations` object holds keys `IN`, `S1`–`S4` and `OUT`, all with the same fields. The station-specific fields (`wear`, `force`) are null where they don't apply.

### 8.3 KPI
```json
{"t":1234.5,"win_s":600,"th_ph":431.2,"line_ct_s":8.35,"lead_s":76.4,
 "A":0.93,"P":0.97,"Q":0.968,"oee":0.873,"yield":0.968,"wip_avg":9.1,
 "down_s":{"S2":{"unplanned":90.0,"planned":0.0}},"mtbf_s":1910,"mttr_s":90,
 "pareto":{"R2":3,"R3":2},"s2":{"health":0.39,"cycles_to_fault":61},
 "check":{"conservation":true,"little_err":0.01}}
```

### 8.4 Commands (`user` is required, because it feeds the audit trail)
`start`, `stop`, `estop {active: true|false}` *(v1.1: a maintained toggle; `reset` does nothing while E-stop is active)*, `reset`, `repair {station}`, `tool_change {station:"S2"}`, `inject_fault {code}`, `refill {bin}`, `set_speed {x: 1|2|5|10|50}`, `set_param {path, value}`.

Example: `{"cmd":"inject_fault","args":{"code":"F201"},"user":"R4"}`

### 8.5 SQLite (`twin.db`)
`parts(serial PK, t_in, t_out, status, reject_codes)`, `part_events(serial, t, station, event, data_json)`, `alarms(code, station, sev, t_raised, t_cleared)`, `state_log(station, t, state, reason)`, `commands(t, wall, user, cmd, args_json)`, `kpi_samples(t, json)`

### 8.6 REST (`:8000/api`)
- `GET /parts/{serial}` returns the timeline and measurements.
- `GET /parts?status=FAIL&limit=50`
- `GET /alarms?limit=100`
- `GET /commands?limit=100`
- `POST /whatif {duration_s, overrides:{path:value}}` returns `{baseline:KPI, scenario:KPI}`. It runs both arms from a deep copy of the current state with the same seed, headless (no sleeping), so 1 h of sim should take under 10 s.

## 9. KPI definitions (exact)
| KPI | Formula |
|---|---|
| Throughput `th_ph` | Good exits in the last 600 sim-s × 6. A cumulative figure is also shown. |
| Station cycle time | Mean of the station's last 20 cycle durations (WAIT → RELEASE, excluding WAIT) |
| Line cycle time `line_ct_s` | Mean interval between consecutive good exits (≈ 3600/th) |
| Lead time `lead_s` | Mean of `t_out − t_in` per part |
| Downtime | Σ time in FAULT (unplanned) and Σ time in MAINT (planned), per station. STARVED and BLOCKED are reported separately as idle loss. |
| OEE (measured at the bottleneck, S2) | A = (planned − S2 FAULT − S2 MAINT) / planned; P = (**10.0 s** design cycle × S2 cycles) / S2 available time; Q = S4 passes / S4 decisions, counted at DECIDE time; OEE = A·P·Q. Planned time excludes STOPPED. |
| Yield (first-pass yield) | S4 passes / S4 decisions. `counts.good` increments at OUT unload; `counts.reject` at the S4 divert. |
| Reject Pareto | Counts **codes** (one unit can carry several), shown next to the total of rejected units |
| MTBF / MTTR | S2 run time / number of F201 events; S2 unplanned downtime / number of F201 events |
| Health (S2) | 1 − wear |
| Cycles-to-fault | Linear fit (`numpy.polyfit`, degree 1) of the last 30 force samples against cycle index, solved for 160 N. Null if the slope ≤ 0. W202 is raised when this is < 60 or force > 135. |
| Validation | Conservation: `in == good + reject + wip`, checked every tick. Little's Law (v1.1, all units): `little_err` = \|wip_avg − (good + reject completions/s) · lead_s\| / wip_avg, which should be < 0.10, measured after a 300 s warm-up over the same window. Pallet conservation: exactly 10 unique pallets across slots, buffers, transit and return. |

## 10. Dashboard (one page, `dashboard/index.html`)
- **Top bar (MVP):** line state, tower light, sim clock, speed selector, Start / Stop / E-stop / Reset buttons, user name field (for the audit trail).
- **Centre (MVP):** SVG layout matching §3. Stations are boxes in state colours, labelled with the current step. Pallets are dots, with the serial on hover. Buffers show their fill level, bins are level bars, and there are counters for In, Good, Reject, WIP and Boxes.
- **Right (MVP):** KPI tiles for Throughput, Line cycle time, Lead time, Downtime (S2 unplanned/planned), OEE with A/P/Q, Yield and WIP.
- **Bottom tabs:**
  - **Trends (MVP):** throughput, S2 force with the 105/140/160 limit lines, OEE.
  - **Alarms & Audit (MVP):** alarm list with raised/cleared times; command log.
  - **Quality (Should):** reject Pareto (R1–R5) and the last 20 parts.
  - **Traceability (Should):** serial search, showing a station timeline with measurements.
  - **Maintenance (Should):** S2 health gauge, cycles-to-fault, Tool Change button, Inject F201 and Repair buttons.
  - **What-if (Should):** pick a parameter, choose a duration and run; shows a side-by-side KPI table with deltas.
  - **Validation (Should):** conservation ✓/✗ and the Little's Law error.

## 11. Faults and scenarios
| Code | Trigger | Effect | Recovery |
|---|---|---|---|
| **F201** (required) | Force > 160 N (from wear) **or** `inject_fault` (the part event is tagged `injected:true`) | **Local fault only (D1):** S2 goes to FAULT, its outputs drop and it holds its pallet; the line stays running. B2 fills up, then S1 BLOCKED, then IN BLOCKED. S3/S4 STARVED. Red lamp and horn. | `I_S2_TOOL_OK` goes to 0 on the trip. `repair` (MTTR 90 s) sets it back to 1 and wear to 0. Then `reset` (it only works with TOOL_OK = 1). S2 resumes at RETRACT, and the unit flows to S4 where it is rejected as R2. |
| F001 | E-stop (the only global stop) | All outputs off, all stations STOPPED | `estop {active:false}`, then `reset`, then `start` |
| F101 / F401 | UV lamp fail / transfer > 5 s | Station FAULT | repair, then reset |
| W202 | Predicted < 60 cycles or force > 135 | Amber lamp, maintenance prompt | `tool_change` (20 s, planned) |

`scenarios/demo.yaml` sets the seed, `initial_wear: 0.3` and speed 10×, so the demo is reproducible.

## 12. Validation (all must pass before the demo)
1. **Conservation** holds every tick (pytest plus the live badge).
2. **Little's Law** error < 10 % over 1 h of sim.
3. **Rate.** With wear disabled, no faults and bins stocked, steady-state throughput is **360/h ± 5 %** (D2).
4. **Determinism.** The same seed gives identical counts after 1 h.
5. **Fault ripple.** After F201, S1 is BLOCKED within 30 s of sim and S3 is STARVED within 25 s.
6. **Control unit tests.** Scripted input sequences produce the expected outputs for P1, P2, P5, P7 and P8.

## 13. Scope tiers
- **MVP (must, by CP4):**
  - Every problem minimum: ≥ 3 stations, material movement, state monitoring, counting, inspection, one fault, KPI dashboard
  - The three suggested KPIs
  - P1–P9 in Python, with ASCII docs
- **Should (by CP5):** U2–U6, P10–P11, and the OpenPLC Editor screenshots
- **Stretch (only if CP4 is green on Day 2):** OpenPLC Runtime with Modbus (SIL); an ESP32 physical E-stop/fault button over MQTT; packaging the twin in Docker

### Requirement coverage
| Requirement | Where |
|---|---|
| ≥ 3 production stations | S1, S2, S3 (+ IN, S4) §4 |
| Material movement | Pallet conveyor, buffers, return loop, bin refill §3–4 |
| Machine status monitoring | PackML-lite states §5, SVG layout §10 |
| Production counting | C_IN/C_GOOD/C_REJECT/C_BOX (P9), counters |
| Quality inspection | S4 vision + leak, R1–R5 §4 |
| Simulated machine fault | F201 with physical cause §4, §11 |
| KPI dashboard | §9–10 |
| Running / Idle / Fault / Count / Rejected | §5 mapping, snapshot `counts` |

## 14. Demo script (5 min, at 10× speed, `demo.yaml`)
1. **(0:00)** Problem, then architecture in one slide (§7 diagram).
2. **(0:40)** Start the line. Point out the pallets moving, states, counters, and KPIs settling. The Validation tab shows conservation ✓.
3. **(1:30)** Click a finished serial to show its full genealogy (U2).
4. **(2:00)** S2 force trend climbs toward 140. R2/R3 rejects appear in the Pareto. Health goes amber and W202 predicts about N cycles to fault (U3).
5. **(2:50)** Let F201 trip (or inject it). Red lamp, B2 fills, S1 goes BLOCKED, S3/S4 STARVED, the downtime clock runs, throughput dips. Show the alarm log.
6. **(3:30)** Repair, then reset: the line recovers and the dip shows in the trend.
7. **(3:50)** What-if: run 1 h with `policy.predictive_tool_change` false vs true and compare OEE/throughput. Then try "S1 cure 3 → 2 s" and show no gain, because S2 is the bottleneck (U4).
8. **(4:30)** Show the P5 ladder screenshot next to the matching `control.py` block: the twin runs real PLC logic (U1).
9. **(4:50)** Close on the coverage table (§13).

## 15. Report outline (≤ 12 pages)
1. Problem
2. Concept and the unique features
3. Process and stations
4. Control layer (I/O list, P1–P11 diagrams)
5. Architecture and data contracts
6. Simulation model and assumptions
7. KPIs
8. Dashboard
9. Validation results
10. What-if findings
11. Limitations and future work (real PLC, OPC UA, physical sensors)
12. Team contributions

## 16. Changelog
- v1.0 — initial brief.
- v1.1 (05 Oct) — Applies DECISIONS D1–D8:
  - F201 is a local fault
  - 2 s transfers, giving a 360/h design rate and a 10 s OEE ideal cycle
  - Little's Law check over all units
  - E-stop is a maintained toggle
  - New tags `Q_OUT_UNLOAD` and `I_OUT_UNLOADED`
  - Repair, resume and stock-consumption rules
  - Quality count definitions
  - Scope cut and new dates: video, report and PPT due **7 Oct**, presentation 8 Oct

  Where this file and `DECISIONS.md` conflict, `DECISIONS.md` §2–3 govern scope and dates.
