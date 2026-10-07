# DECISIONS.md — Approved rulings for CP0 (brief v1.1)
**Status: APPROVED, 05 Oct 2026.** These rulings override any conflicting text in `skills.md`, `roles.md` and `ACTION_PLAN.md`. `PROJECT_BRIEF.md` has been updated to v1.1 to match.

## 0. What to do with the review pack
**Adopt as-is:**
- Requirement → evidence matrix (p.2)
- Validation and evidence register, including the separate **pallet-conservation** check and the evidence file names (p.8)
- Report plan (p.9), PPT storyboard (p.10), viva answers (p.11–12)
- The "no unmeasured numbers" rule: every figure in the report, PPT or video must come from a real run saved in `docs/evidence/`

**Replaced:** the pack's checkpoint schedule. It started CP0 at 15:00 today, which is already too late, and it ignored college hours. The new schedule is §3.

---

## 1. Rulings
### D1 — Local overload vs. global stop → **local fault**
- E-stop (F001) is the **only** global stop.
  - P1-R1 seal-in uses `F001` in place of `M_ANY_FAULT`.
  - `M_ANY_FAULT` is now used only for the tower light and horn.
- Station faults (`F_S1`…`F_S4`) gate **only** that station's outputs and its P2 release.
- P1 tests are updated: injecting F201 must **not** drop `M_SYS_RUN`.

### D2 — Transfer semantics and design rate → **360/h**
Transfer rules:
- Release frees the source slot immediately.
- The pallet is then "in transit" for 2.0 s, owned by the transfer, and the destination place is **reserved**.
- Transfers may run while stations are processing. A station cannot pre-stage its next pallet.
- Buffers feed their downstream station automatically (accumulation conveyor) whenever the station slot is empty and unreserved.

Consequence: S2's cycle = 8 s process + 2 s index = **10 s**.
- **Design rate = 360/h.** 450/h is labelled "process-only ideal".
- Rate test: steady state at 360/h ± 5 %, with wear and faults disabled and bins stocked.
- OEE ideal cycle = **10 s**.
- Transfer time stays at 2 s. Don't change it just to make a test pass.

### D3 — Little's Law population → **all completions**
- Check: `wip_avg ≈ (good + reject completions per s) × lead_s_all`.
- Window: after a 300 s warm-up, over the same 3600 s window. WIP is time-averaged per tick; lead time is the mean over units completed in the window.
- `th_ph` on the dashboard stays good-only. No payload keys change.

### D4 — E-stop release → **maintained toggle**
- `estop` now takes `args {active: true|false}`. This is a contract change and is recorded in brief v1.1 §8.4.
- The HMI E-stop is a latching red button.
- Recovery order: `estop {active:false}` → `reset` → `start`.
- `reset` while `I_ESTOP_OK = 0` does nothing.

### D5 — I/O sufficiency → **2 new tags, plus plant-side reservation**
- **New tags:** `Q_OUT_UNLOAD` %QX6.0 and `I_OUT_UNLOADED` %IX6.5.
- **`I_Bn_FULL`** = (pallets occupied + reserved in Bn) ≥ capacity. The plant computes it, so no extra handshake tags are needed.
- Steps with no done-sensor (S1 CURE, S3 VERIFY, S4 LEAK and DECIDE) use PLC timers `T_<St>_<STEP>`.
- R1 and R2 write one worked transfer (S1 → B2 → S2, as a tag-level trace) into `docs/plc/P2.md` before CP1.

### D6 — Repair, resume point and counters
- On F201, the plant sets `I_S2_TOOL_OK = 0`.
- `repair {S2}` starts the 90 s MTTR. When it ends: `I_S2_TOOL_OK = 1` and wear = 0.
- `reset` clears F201 only if `I_S2_TOOL_OK = 1`.
- S2 resumes at **RETRACT**. The affected unit keeps its recorded force and flows on to S4, where it is rejected as R2 naturally. Units hit by an injected fault are tagged `injected:true` in their part events.
- Wear increments when PRESS completes. The trip cycle counts toward wear.
- **Stock is consumed** at these points: barrel at PICK, plunger and stopper at PRESS start, cap at CAP_PRESS start.
- `C_BOX` is the PLC's modulo-10 packing counter. `counts.boxes` in the snapshot is cumulative and computed in the MES. They are separate on purpose.

### D7 — Quality counts
- `Q` = S4 passes ÷ S4 decisions, counted at DECIDE time.
- `counts.good` increments at OUT unload. `counts.reject` increments at the S4 divert.
- Conservation stays `in = good + reject + wip`.
- The Pareto counts **codes**, so one unit can appear under several codes. The total of rejected **units** is shown next to it.

### D8 — What-if fairness
Both arms run the same automatic operator policy:
- F201 → `repair` immediately; `reset` as soon as `I_S2_TOOL_OK = 1`.
- Bins auto-refill.

The only difference between arms is the overridden parameter. For the maintenance comparison, that is `policy.predictive_tool_change`: when true, W202 triggers a tool change at S2's next WAIT step.

Cloning: `deepcopy` of the full state, including the numpy `Generator` objects (their state copies with them). The live state must be unchanged afterwards (test this).

### Demo wear timing → keep the config, measure the result
With a 10 s cycle and `initial_wear 0.3`, the mean force crosses 140 N after about 50 cycles (≈ 50 s of video at 10×) and 160 N after about 175 cycles (≈ 2.9 min). Noise moves both earlier or later.
- Keep seed 7, initial wear 0.3, and 10×.
- Because the deliverable is now a **recorded video**, cut the waiting time in the edit, or switch to 50× while waiting.
- If you inject F201 instead, label it **"injected"** on screen.

---

## 2. Scope cut (the deadline moved to 7 Oct)
| Item | Decision |
|---|---|
| MVP: every official minimum, P1–P9, 3 KPIs, §12 tests | **Keep.** This is non-negotiable. |
| U3 predictive (W202, cycles-to-fault, tool change) | **Keep.** It is part of how the fault happens, so it costs little. |
| U2 traceability (`/api/parts/{serial}` + modal) | **Keep** |
| U6 audit trail | **Keep.** It is already in the contract. |
| U4 what-if (API + side-by-side table) | **Only if CP4 is on time.** Otherwise list it as future work. |
| U5 live Validation tab | **Cut.** Run it as pytest only, and show the output in the report. |
| Quality tab | **Cut.** Show the Pareto as one chart in Trends if it costs under 30 min. |
| P10 jam watchdog, P11 material logic | **Cut.** List them as future work. Bin starvation still works through the S2/S3 WAIT transitions. |
| OpenPLC Editor screenshots | **P1, P2 and P5 only.** The rest stay as ASCII and SFC in `docs/plc/`. |
| All Stretch items (OpenPLC Runtime, ESP32, Docker) | **Cut** |

## 3. Schedule (IST)
These times assume evenings plus any free slots. If college hours collide, shift the times, but **never reorder the gates**.

| Gate | When | Exit evidence |
|---|---|---|
| CP0 | **5 Oct 17:00** | Five names assigned to R1–R5; faculty approval requested; repo skeleton; brief v1.1 + `DECISIONS.md` committed; `tags.py` including the D5 tags; JSON fixtures |
| CP1 | 5 Oct 22:00 | Mock snapshot → broker → live SVG; one pallet moves headless IN → S2 under D2 semantics |
| CP2 | 6 Oct 14:00 | Full headless flow under `control.py`; part and pallet conservation pass; 1 h of sim runs in < 10 s |
| CP3 | 6 Oct 19:00 | Live dashboard with controls; F201 trip → repair → reset end-to-end; E-stop toggle works |
| CP4 | **6 Oct 23:30** | MVP + U3/U2/U6; all §12 tests pass; tag `v0.9`; anything not started is cut |
| CP5 | 7 Oct 10:00 | Feature freeze, tag `v1.0`; evidence run saved to `docs/evidence/` |
| CP6 | 7 Oct 14:00 | **Video recorded**; report PDF and PPT final, with every number taken from the evidence run |
| CP7 | 7 Oct 16:00 | Submitted. Submit earlier if the faculty cutoff time is earlier; confirm it today. |
| — | 8 Oct | Two timed rehearsals and a viva drill before the session |

## 4. Role assignment rule
- **R1** goes to whoever has the most free hours on 5–7 Oct **and** can reason about ladder logic.
- **R5** owns the video.
- Each of the five members takes exactly one role. Record the mapping here:

| Role | Member |
|---|---|
| R1 Lead/Control | |
| R2 Plant | |
| R3 Data/Backend | |
| R4 Dashboard | |
| R5 QA/Docs/Video | |

## 5. Rulings — 6 Oct 2026 (final scope)
These override the scope cut in §2 where they conflict.

### D9 — Control layer → OpenPLC with a live link to the twin
- OpenPLC Runtime is the PLC. The twin connects over Modbus TCP in **PLC mode** (`launch.py --plc`). Internal mode stays the default.
- The PLC owns: run permissive, E-stop latch, F201 detection and reset permissive, tower light, horn, counters and the link watchdog. The twin keeps sequences, physics, quality and KPIs.
- Specification: `docs/plc/PLC_SPEC.md`. Every signal: `docs/plc/tag_dictionary.csv`.
- If the 18:30 connection test fails, the GX Works3 + GT Designer3 standalone path (PLC_SPEC §8) is used instead. Only one PLC platform is built.

### D10 — New alarm F002 and new tags
- **F002 "PLC link lost"** (FAULT, global stop): either side stops seeing the other's heartbeat for 1 s. Recovery: link restored → Reset → Start.
- New signals for the link, all listed in `tag_dictionary.csv`: command pulses, sequence numbers (`S2_PRESS_SEQ`, `GOOD_SEQ`, `REJECT_SEQ`, `IN_SEQ`), `S2_VERDICT_SEQ`, heartbeats, `M_S2_REPAIRED`, `F201_INJECTED`.
- In PLC mode, S2 waits after PRESS until the PLC has evaluated that force sample (the INSERT permissive).

### D11 — OPC UA, what-if and terminology
- The twin exposes a **read-only OPC UA server**. Node IDs are listed in `tag_dictionary.csv`; it is verified with UaExpert.
- The what-if sandbox (U4) is reinstated as a MUST and is the main decision-support feature.
- S2 maintenance is described as **model-based condition monitoring with force-trend extrapolation**. It is not called AI or ML anywhere.
- FUXA is the operator HMI on the OpenPLC path, bound directly to PLC tags (SHOULD).

### D12 — Demo profile, W202 smoothing and rolling OEE
- **Demo profile** `config/profiles/demo.yaml` (`launch.py --profile demo`): fresh S2 tool, wear 0.010 per cycle, W202 trend warning at < 25 cycles. Seed 7 at 10× gives, in video time: W202 ≈ 41 s, first R2 ≈ 45 s, natural F201 ≈ 87 s. The dashboard shows a "Demo profile" badge for every run that uses it.
- **W202** is raised on the **mean of the last 5 press forces** > 135 N (not a single sample), or when the force trend predicts fewer than `warn.cycles` cycles to 160 N. The trend needs at least **15** samples. Thresholds live in `config/line.yaml` under `stations.S2.warn`.
- **Rolling OEE**: the same A × P × Q formula over the trailing 600 sim-s (`kpi.oee_win`), next to the run-to-date value. The dashboard OEE tile and trend show the rolling value, so a fault dip and its recovery are both visible.

### D13 — Operator HMI over OPC UA
- The HMI is **FUXA** (open-source HMI/SCADA), project `hmi/syringetwin_hmi.json`, connected to the twin as an **OPC UA client**.
- The twin's OPC UA server stays read-only except `Line1.HMI.*`: Start, Stop, Reset, EStopEngage, EStopRelease, RepairS2, ToolChangeS2, InjectF201 (Boolean pulses) and SpeedCmd (Int32). Each write runs the normal command path, is audited as user "HMI (OPC UA)", and its outcome is published in `Line1.HMI.LastResult`.
- `Line1.Display.*` publishes pre-formatted strings for panels; the raw numeric nodes are unchanged.
