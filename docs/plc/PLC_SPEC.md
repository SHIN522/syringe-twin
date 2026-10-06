# PLC control layer — specification

Status: **v1.0, 6 Oct 2026.** Governs `plc/openplc/` (primary) and `plc/gxworks3/` (fallback).
Signal names, addresses and OPC UA nodes are defined once in [`tag_dictionary.csv`](tag_dictionary.csv); this file defines behaviour.

## 1. Purpose and scope

The PLC is a small but real IEC 61131-3 controller that **owns the supervisory and safety decisions** of the cell while the Python twin remains the plant model and the MES (ISA-95 L1/L2 vs L3).

| Function | Brief ID | Owner in PLC mode |
|---|---|---|
| Start/Stop seal-in, run permissive | P1 | **PLC** |
| E-stop chain and latch (F001), recovery: release → Reset → Start | P1, P8 | **PLC** |
| S2 force monitoring, F201 overload latch | P5 | **PLC** |
| S2 INSERT permissive (twin waits for the PLC verdict on every press sample) | P5 | **PLC** |
| F201 reset only after repair (`I_S2_TOOL_OK`) | P8 | **PLC** |
| Tower light (flashing red), horn | P1 | **PLC** |
| Production counters C_IN, C_GOOD, C_REJECT, C_BOX (PV 10) | P9 | **PLC** |
| Twin ↔ PLC link watchdog (F002) | new | **PLC + twin** |
| S2 release interlock (done ∧ B3 room ∧ run ∧ ¬F201) | P2 | **PLC** — SHOULD |
| Station sequences, other transfers, physics, quality, inspection, KPIs | — | Twin (unchanged) |

Not in scope: re-implementing the full station sequences or plant in ladder.

### Control modes

- **Internal** (default): the twin's `control.py` makes every decision. All existing tests, the hosted browser copy and Streamlit run this mode unchanged.
- **PLC**: `launch.py --plc HOST[:PORT]`. The twin bridge exchanges registers with OpenPLC Runtime over Modbus TCP every 20 ms wall time. The decisions in the table above come only from the PLC; the twin's own F201 trip check is disabled (`control.f201_source: plc`).

## 2. Platform and timing

| Item | Value |
|---|---|
| Runtime | OpenPLC Runtime v3, Modbus TCP server enabled (Settings → Modbus, port 502) |
| Editor | OpenPLC Editor; LD for P1/P5/P8/P9, ST for the I/O mapping POU |
| Task | `TASK main(INTERVAL := T#20ms, PRIORITY := 0)` |
| Bridge cycle | 20 ms wall (Python `pymodbus` client) |
| Command pulses | Bridge holds a command register at 1 for **200 ms wall** (≥ 10 scans); the PLC uses rising edges |
| Speed limit in PLC mode | 1×–10× (validated); 50× not supported |
| Event signals | Sequence numbers, not pulses (press sample, good, reject), so no event is lost between scans |
| Power-up | The PLC normally scans before the twin's first write, sees `I_ESTOP_OK` = 0 and latches F001. **Press Reset once after connecting**, then Start. This is the intended fail-safe behaviour. |
| Watchdog arming | The PLC-side watchdog (P8-R3) arms on the first twin heartbeat, so the PLC can be tested alone in the Monitoring page without tripping F002. |
| Measured handshake cost | Twin waits ~0.3–0.4 sim-s per S2 cycle for the verdict at 10× (S2 cycle 8.4 s vs 8.0 s); round trip 0.8 ms on localhost |

OpenPLC Modbus mapping (v3): coils = `%QX` (coil n = byte·8 + bit), holding registers 0–1023 = `%QW`, holding registers 1024–2047 = `%MW`. A Modbus master cannot write `%IX`/`%IW`, therefore **all twin → PLC signals are `%MW` registers** and all PLC → twin signals are `%QX` coils or `%QW` registers.

## 3. Program organisation

| POU | Language | Content |
|---|---|---|
| `IO_MAP` | ST | Located variables; INT → BOOL conversion; rising edges (`R_TRIG`); sequence-number change detection; heartbeat counter |
| `P1_MASTER` | LD | Run seal-in, E-stop latch, blink oscillator, tower light, horn |
| `P5_S2_FORCE` | LD | New-sample handling, force compare, F201 set, verdict echo, injected fault |
| `P8_ALARMS` | LD | Repair acknowledgement, F201 reset, F002 watchdog and reset, any-fault/any-warn summaries |
| `P9_COUNTERS` | LD | CTU counters and box logic |
| `P2_S2_RELEASE` | LD | S2 release permit — SHOULD |

Rung comments carry the rung ID (for example `P5-R2`). The twin's matching Python code carries the same ID.

## 4. Logic

Notation: `_RE` = rising edge from `R_TRIG`; `NEW_x` = sequence number changed this scan.

### IO_MAP (ST)

```iecst
START_B := CMD_START <> 0;   STOP_B := CMD_STOP <> 0;   RESET_B := CMD_RESET <> 0;
ESTOP_OK := I_ESTOP_OK <> 0; TOOL_OK := I_S2_TOOL_OK <> 0;
TRIG_START(CLK := START_B);  START_RE := TRIG_START.Q;
TRIG_RESET(CLK := RESET_B);  RESET_RE := TRIG_RESET.Q;
TRIG_INJ(CLK := CMD_INJECT_F201 <> 0); INJECT_RE := TRIG_INJ.Q;
TRIG_TOOL(CLK := TOOL_OK);   TOOL_OK_RE := TRIG_TOOL.Q;

NEW_PRESS  := S2_PRESS_SEQ <> LAST_PRESS_SEQ;
NEW_GOOD   := GOOD_SEQ     <> LAST_GOOD_SEQ;   LAST_GOOD_SEQ   := GOOD_SEQ;
NEW_REJECT := REJECT_SEQ   <> LAST_REJECT_SEQ; LAST_REJECT_SEQ := REJECT_SEQ;
NEW_IN     := IN_SEQ       <> LAST_IN_SEQ;     LAST_IN_SEQ     := IN_SEQ;
HB_CHANGED := HEARTBEAT    <> LAST_HB;         LAST_HB         := HEARTBEAT;
PLC_HEARTBEAT := PLC_HEARTBEAT + 1;            (* twin-side watchdog *)
```

`LAST_PRESS_SEQ` is updated in P5-R3, after the force has been evaluated.

### P1 — master control

```
P1-R1  Run seal-in (station faults do NOT drop the line; only F001/F002 do — DECISIONS D1)
      START_RE        STOP_B     F001     F002                 M_SYS_RUN
  ----| |------+------|/|-------|/|------|/|--------------------( )----
     M_SYS_RUN |
  ----| |------+

P1-R2  E-stop latch
      ESTOP_OK                                                  F001
  ----|/|--------------------------------------------------------(S)---
      RESET_RE     ESTOP_OK                                     F001
  ----| |-----------| |------------------------------------------(R)---

P1-R3  Blink oscillator 0.5 s / 0.5 s
      BLINK_T2.Q          BLINK_T1 TON PT=T#500ms → BLINK_T2 TON PT=T#500ms
  ----|/|------[BLINK_T1]------[BLINK_T2]                        BLINK = BLINK_T1.Q

P1-R4  Red lamp + horn
      M_ANY_FAULT    BLINK                                     Q_LAMP_RED
  ----| |-----------| |------------------------------------------( )----
      M_ANY_FAULT                                                Q_HORN
  ----| |--------------------------------------------------------( )----

P1-R5  Amber lamp (warning or any station blocked, no fault)
      M_ANY_FAULT    TWIN_WARN                                 Q_LAMP_AMBER
  ----|/|------+-----| |------+-------------------------------------( )----
               |   ANY_BLOCKED|
               +-----| |------+

P1-R6  Green lamp
      M_SYS_RUN    M_ANY_FAULT   Q_LAMP_AMBER                  Q_LAMP_GREEN
  ----| |-----------|/|-----------|/|---------------------------------( )----
```

The lamp precedence (red > amber > green > off) matches the twin's `snapshot()['lamp']`.

### P5 — S2 force monitoring and F201

```
P5-R1  Overload: new press sample above trip limit
      NEW_PRESS    [GT  AI_S2_FORCE, TRIP_SP]                     F201
  ----| |----------[ AI_S2_FORCE > 1600 (160.0 N) ]-----------------(S)---
                                                              M_S2_REPAIRED
                                                          +---------(R)---

P5-R2  Injected overload (operator test, from the dashboard)
      INJECT_RE                                                     F201
  ----| |------------------------------------------------------+----(S)---
                                                               |  F201_INJECTED
                                                               +----(S)---

P5-R3  Verdict echo — releases the twin's INSERT step for this sample
      NEW_PRESS              MOVE S2_PRESS_SEQ → S2_VERDICT_SEQ
  ----| |-----------------[  MOVE S2_PRESS_SEQ → LAST_PRESS_SEQ ]
```

Rung order matters: P5-R1 runs before P5-R3, so the twin always sees the F201 coil and the verdict in the same read. The twin continues S2 to INSERT only when `S2_VERDICT_SEQ == S2_PRESS_SEQ` and `F201 = 0`.

### P8 — alarms and recovery

```
P8-R1  Repair acknowledged (tool OK returns while F201 is latched)
      F201       TOOL_OK_RE                                    M_S2_REPAIRED
  ----| |---------| |---------------------------------------------(S)---

P8-R2  F201 reset — requires a completed repair (DECISIONS D6)
      RESET_RE    F201    M_S2_REPAIRED    TOOL_OK                 F201
  ----| |---------| |-------| |--------------| |----------------+----(R)---
                                                               | M_S2_REPAIRED
                                                               +----(R)---
                                                               | F201_INJECTED
                                                               +----(R)---

P8-R3  Link watchdog: twin heartbeat unchanged for 1 s (armed after the first heartbeat)
      LINK_SEEN   HB_CHANGED      T_WD TON PT=T#1s                 F002
  ----| |---------|/|-----------[T_WD]----------------------------(S)---

P8-R4  F002 reset — only with a live link
      RESET_RE     T_WD.Q                                           F002
  ----| |-----------|/|-------------------------------------------(R)---

P8-R5  Summaries
      F001 ─┬─ F201 ─┬─ F002 (OR)                               M_ANY_FAULT
                                                               ----( )----
```

`M_S2_REPAIRED` uses the rising edge of `TOOL_OK`, so a Reset that arrives before the twin has dropped `TOOL_OK` cannot clear F201.

### P9 — counters

```
P9-R1  C_IN      CTU  CU := NEW_IN
P9-R2  C_GOOD    CTU  CU := NEW_GOOD
P9-R3  C_REJECT  CTU  CU := NEW_REJECT
P9-R4  C_BOX     CTU  CU := NEW_GOOD, PV := 10, R := C_BOX.Q   → BOX_FILL := C_BOX.CV
P9-R5  C_BOX.Q ──► BOXES_TOTAL := BOXES_TOTAL + 1 (ADD)
```

PLC counters count from link start. The twin reports a consistency check: Δ`counts.good` since link start = `C_GOOD`.

### P2 — S2 release permit (SHOULD)

```
P2-R1   S2_DONE    B3_ROOM    M_SYS_RUN    F201              S2_RELEASE_PERMIT
  ------| |--------| |---------| |----------|/|-------------------( )----
```

## 5. Twin-side contract (implemented in `twin/plc_bridge.py`)

| PLC signal / condition | Twin effect |
|---|---|
| `M_SYS_RUN` | `state.run` follows the coil. Dashboard Start/Stop become 200 ms `CMD_START`/`CMD_STOP` pulses, audited as "sent to PLC". |
| Dashboard E-stop engage/release | `I_ESTOP_OK` = 0/1 (maintained). `estop_latched` mirrors coil `F001`. |
| Dashboard Reset | 200 ms `CMD_RESET` pulse |
| `F201` rising | `trip_s2(state, injected=F201_INJECTED)` — same effect as internal mode: S2 holds its pallet, line keeps running, B2 fills, S1 blocks, S3/S4 starve |
| `F201` falling | Existing S2 resume path: clear twin F201 alarm, resume at RETRACT |
| `S2_VERDICT_SEQ ≠ S2_PRESS_SEQ` | S2 waits at the end of PRESS (the INSERT permissive). Timeout 1 s wall → F002. |
| Modbus error or `PLC_HEARTBEAT` unchanged for 1 s | `state.run = False`, twin alarm F002 "PLC link lost", dashboard banner. Recovery: link restored → Reset → Start. |
| Repair S2 (dashboard) | Unchanged twin repair (90 sim-s); `tool_ok` → `I_S2_TOOL_OK` |

## 6. PLC verification cases

Run in OpenPLC Runtime with the Monitoring page (or forced values) and again in PLC mode with the twin. Results go into `docs/evidence/test_matrix.md`.

| ID | Steps | Expected |
|---|---|---|
| PLC-01 | `I_ESTOP_OK`=1, pulse `CMD_START` | `M_SYS_RUN`=1, green on |
| PLC-02 | Pulse `CMD_STOP` while running | `M_SYS_RUN`=0, green off, no alarm |
| PLC-03 | `I_ESTOP_OK`=0 while running | `F001`=1, `M_SYS_RUN`=0, red flashing, horn |
| PLC-04 | After PLC-03: pulse `CMD_RESET` with `I_ESTOP_OK`=0 | `F001` stays 1 |
| PLC-05 | `I_ESTOP_OK`=1, `CMD_RESET`, then `CMD_START` | `F001`=0, then `M_SYS_RUN`=1 |
| PLC-06 | `AI_S2_FORCE`=1450, increment `S2_PRESS_SEQ` | `F201`=0, `S2_VERDICT_SEQ` = `S2_PRESS_SEQ` |
| PLC-07 | `AI_S2_FORCE`=1612, increment `S2_PRESS_SEQ` | `F201`=1, `M_SYS_RUN` **still 1** (local fault), red flashing |
| PLC-08 | After PLC-07: `CMD_RESET` with `I_S2_TOOL_OK`=1 (no repair yet) | `F201` stays 1 |
| PLC-09 | `I_S2_TOOL_OK` 0 → 1, then `CMD_RESET` | `M_S2_REPAIRED`=1, then `F201`=0 |
| PLC-10 | Increment `GOOD_SEQ` 10 times, `REJECT_SEQ` twice | `C_GOOD`=10, `C_REJECT`=2, `BOXES_TOTAL`=1, `BOX_FILL`=0 |
| PLC-11 | Freeze `HEARTBEAT` for > 1 s | `F002`=1, `M_SYS_RUN`=0 |
| PLC-12 | Resume `HEARTBEAT`, `CMD_RESET`, `CMD_START` | `F002`=0, `M_SYS_RUN`=1 |
| PLC-13 | `TWIN_WARN`=1, no fault | Amber on, green off |

## 7. Connection test (tonight, before any bridge code)

1. Install OpenPLC Runtime (Windows installer, or WSL Ubuntu `./install.sh linux`). Open `http://localhost:8080`; change the default login password.
2. Settings → enable Modbus server, port 502. Save.
3. Programs → upload `plc/openplc/spike.st` → compile → Start PLC.
4. Run `tools/plc_probe.py --host 127.0.0.1` (written in step 2). Pass criteria:
   - writing `%MW0` = 41 reads back `%QW0` = 42 (holding-register mapping and program execution);
   - writing `%MW1` = 1 reads coil `%QX0.0` = 1 (coil mapping);
   - `%QW1` increases by about 50 per second (20 ms task).
5. **Go / no-go at 18:30.** Fail → GX Works3 fallback (§8).

## 8. Fallback: GX Works3 + GT Designer3

Same POUs and global labels, with the device column of `tag_dictionary.csv` (FX5U). Differences:

- Inputs come from GT Designer3 switches (M bits) instead of Modbus registers.
- A clearly labelled `PLANT_SIM` program supplies `AI_S2_FORCE` (base + wear ramp per S2 cycle), the sequence numbers and `I_S2_TOOL_OK` (repair timer), so the PLC and HMI can be demonstrated standalone in GX Simulator3 + GT Simulator3.
- The twin runs in internal mode; the link to the twin is listed as future work.
