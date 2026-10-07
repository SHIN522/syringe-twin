# Validation test matrix

Generated 2026-10-07T20:32:30+05:30 by `python tools/validation_matrix.py`. Every *actual* value was measured in that run (seed 7). PLC-mode rows T33–T36 use the Modbus stand-in of `syringetwin.st`; PLC-xx rows are run on OpenPLC Runtime by `tools/plc_acceptance.py`.

**Automated: 36/36 PASS.**

| ID | Area | Test | Expected | Actual (measured) | Result |
|---|---|---|---|---|---|
| T01 | Start | Start from idle loads the first part | run = true; first serial loaded within 5 sim-s; IN RUNNING | run = True; SYR-B07-000001 loaded after 0.2 sim-s; IN RUNNING | **PASS** |
| T02 | Stop | Stop freezes production and keeps progress | All stations STOPPED; pallets, buffers, transfers and counts unchanged for 30 sim-s | all STOPPED = True; state unchanged over 30 sim-s = True | **PASS** |
| T03 | Stop | Restart after Stop resumes from the same point | Production continues; no part lost or duplicated | loaded 6 → 19; in = good + reject + WIP (10 + 0 + 9) | **PASS** |
| T04 | E-stop | E-stop stops every station and latches F001 | run = false; F001 active; all stations STOPPED | run = False; active alarms ['F001']; stations {'STOPPED'} | **PASS** |
| T05 | E-stop | Reset and Start are refused while E-stop is engaged | Reset leaves F001 latched; Start rejected | latched after Reset = True; Start → "Release E-stop and reset its latch before Start." | **PASS** |
| T06 | E-stop | Recovery order: release → Reset → Start | Start refused before Reset; running after Reset + Start | Start before Reset refused = True; after Reset + Start run = True | **PASS** |
| T07 | F201 | Natural overload from tool wear | F201 when a press force exceeds 160 N (demo profile) | F201 at 869.2 sim-s; force 161.9 N on SYR-B07-000086; wear 0.86 | **PASS** |
| T08 | F201 | Injected overload is traceable as injected | F201 latched; part event tagged injected = true | S2 fault F201; SYR-B07-000014 injected tag = True | **PASS** |
| T09 | Fault propagation | F201 is local: the line keeps running | run = true after F201; S2 FAULT; tower light RED | run = True; S2 FAULT; lamp RED | **PASS** |
| T10 | Fault propagation | Upstream blocks and downstream starves | S1 BLOCKED within 30 sim-s; S3 STARVED within 25 sim-s; IN BLOCKED | after the trip: S1 BLOCKED at 4.1 sim-s, S3 STARVED at 5.0 sim-s, IN BLOCKED at 0.0 sim-s | **PASS** |
| T11 | Fault propagation | Throughput drops while S2 is down | No good exit once the line has drained; downtime accumulates | good units 54 → 54 over 180 sim-s; S2 unplanned downtime 300 s | **PASS** |
| T12 | Reset/recovery | Reset before repair is refused | F201 stays latched | S2 fault after Reset = F201; "F201 remains latched: repair must finish before reset." | **PASS** |
| T13 | Reset/recovery | Repair (90 sim-s) then Reset resumes S2 at RETRACT | tool_ok after 90 s, wear = 0; S2 resumes at RETRACT; line produces again | repair took 90.0 sim-s, wear after repair 0.000; resumed at RETRACT; good 54 → 71 in 200 sim-s | **PASS** |
| T14 | Reset/recovery | Affected part is rejected R2 and keeps its trace | Part exits as FAIL with R2; overload event in its history | SYR-B07-000086: FAIL ['R2', 'R3']; overload event in trace = True; 42 events | **PASS** |
| T15 | Inspection | Every decision matches its measurements | R1–R5 assigned exactly when a limit is violated; PASS parts are inside every limit | 141 inspection decisions checked against raw measurements; 0 mismatches | **PASS** |
| T16 | Inspection | Force out of window raises leak failures | Mean leak rate of out-of-window parts > 5 Pa/s; in-window ≈ 2 Pa/s | out-of-window mean leak 8.09 Pa/s (n = 85); in-window 2.01 Pa/s (n = 56) | **PASS** |
| T17 | Inspection | Rejected parts are diverted at S4, never packed | Every FAIL part leaves at S4 (diverted); every PASS part is unloaded at OUT | 141 completed parts checked; 0 routed incorrectly | **PASS** |
| T18 | Counting | Part conservation on every tick | in = good + reject + WIP on each of 36 000 ticks (1 sim-hour) | max imbalance 0 required, measured 0; final in 148 = 56 + 85 + 7 | **PASS** |
| T19 | Counting | Ten unique pallets are always accounted for | Pallet check true on every tick; WIP ≤ 10 | pallet check failures 0; max WIP 10 | **PASS** |
| T20 | Counting | Boxes of ten | boxes = good // 10 throughout the run | 3600 checks; good 356 → boxes 35; mismatches 0 | **PASS** |
| T21 | Material flow | FIFO: parts finish in the order they were loaded | Completion order equals serial order | 141 completions; in serial order = True | **PASS** |
| T22 | Material flow | Empty hopper starves IN; refill arrives after 30 sim-s | No load while empty; IN STARVED (material empty); production resumes after refill | loads while empty: 0; production resumed 30.2 sim-s after emptying | **PASS** |
| T23 | Material flow | Low stock raises a warning and an automatic refill | W001 below 30 barrels; hopper back to 300 after 30 sim-s | W001 after 3.4 sim-s; hopper refilled to 300 after 30.0 sim-s | **PASS** |
| T24 | Material flow | Planned tool change waits for the cycle boundary | 20 sim-s planned downtime; no unplanned downtime; wear reset | planned 20.0 s; unplanned 0.0 s; wear after 0.008 | **PASS** |
| T25 | Validation | Design rate with wear and noise off | 360 good units/h ± 5 % after a 300 sim-s warm-up | 360 good units in 3600 sim-s (+0.0 %) | **PASS** |
| T26 | Validation | Little's Law on the same window | \|WIP − λ·W\| / WIP < 10 % | WIP 8.99; λ 360/h; W 89.9 s; error 0.00% | **PASS** |
| T27 | Validation | Determinism: same seed, same result | Identical counts and last force after 1000 sim-s | run A {'in': 105, 'good': 56, 'reject': 40}; run B {'in': 105, 'good': 56, 'reject': 40}; identical = True | **PASS** |
| T28 | What-if | The live twin is never modified | Live state identical before and after a what-if run | fingerprint unchanged = True | **PASS** |
| T29 | What-if | "Keep running" forecasts the live line | Forecast next-F201 time equals the live outcome (± 1 tick) | forecast 229.2 sim-s; live 229.2 sim-s | **PASS** |
| T30 | What-if | Maintenance decision | Condition-based changes recommended; fewer F201 and rejects in 5/5 seeds | good/h: keep 217, change now 234, condition-based 337; F201 2.0 → 0.0; wins 5/5 | **PASS** |
| T31 | What-if | Speeding up a non-bottleneck gives nothing | S1 cure 3 → 2 s: < 2 % change; keep current recommended | good 336 → 336 (+0.0%); bottleneck S2; recommendation: keep | **PASS** |
| T32 | What-if | Speeding up the bottleneck moves it | S2 insert 3 → 0.5 s: > 10 % gain; design bottleneck moves S2 → S1 | good 336 → 429 (+27.7%); design capacity 360 → 450/h, bottleneck S2 → S1 | **PASS** |
| T33 | PLC mode | Start/Stop through the PLC run permissive | Twin runs only while M_SYS_RUN = 1 | before Start run = False; after Start True; after Stop stopped = True | **PASS** |
| T34 | PLC mode | PLC detects the overload and gates recovery | F201 coil on force > 160 N; Reset refused until repair; resume after Reset | F201 at force 161.1 N; held after early Reset = True; cleared after repair + Reset = True | **PASS** |
| T35 | PLC mode | Lost PLC link stops the line safely | F002 within ~1 s; line stopped; Reset needed after the link returns | stopped with F002 = True; Start refused before Reset = True; running after Reset + Start = True | **PASS** |
| T36 | PLC mode | PLC counters agree with the twin | C_IN, C_GOOD, C_REJECT match twin counts over 600 sim-s | PLC 64/48/7 vs twin 64/48/7; consistent = True | **PASS** |
| PLC-01 | OpenPLC Runtime | Start pulse sets run permissive and green lamp | See PLC_SPEC.md §6 | run True, green True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-02 | OpenPLC Runtime | Stop pulse drops run | See PLC_SPEC.md §6 | run False, green False, any fault False (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-03 | OpenPLC Runtime | E-stop latches F001, red flashing, horn | See PLC_SPEC.md §6 | F001 True, run False, horn True, red lamp flashing True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-04 | OpenPLC Runtime | Reset ignored while E-stop open | See PLC_SPEC.md §6 | F001 after Reset with E-stop open: True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-05 | OpenPLC Runtime | Release → Reset → Start recovers | See PLC_SPEC.md §6 | F001 cleared True, run after Start True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-06 | OpenPLC Runtime | Force 145.0 N: no F201, verdict echoed | See PLC_SPEC.md §6 | force 145.0 N: F201 False, verdict 1 = sample 1 (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-07 | OpenPLC Runtime | Force 161.2 N: F201 set, line keeps running | See PLC_SPEC.md §6 | force 161.2 N: F201 True, run still True, verdict echoed True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-08 | OpenPLC Runtime | Reset before repair refused | See PLC_SPEC.md §6 | F201 after Reset without repair: True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-09 | OpenPLC Runtime | Repair (TOOL_OK 0→1) then Reset clears F201 | See PLC_SPEC.md §6 | repair acknowledged True, F201 after Reset False (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-10 | OpenPLC Runtime | Counters and box of ten | See PLC_SPEC.md §6 | +10 good, +2 reject, +1 box, box fill 0 → 0 (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-11 | OpenPLC Runtime | Frozen heartbeat trips F002 and drops run | See PLC_SPEC.md §6 | heartbeat frozen 1.5 s: F002 True, run False (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-12 | OpenPLC Runtime | Heartbeat back, Reset, Start recovers | See PLC_SPEC.md §6 | F002 cleared True, run after Start True (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
| PLC-13 | OpenPLC Runtime | Twin warning gives amber lamp | See PLC_SPEC.md §6 | amber True, green False (OpenPLC Runtime v3, 2026-10-07T13:34:01+05:30) | **PASS** |
