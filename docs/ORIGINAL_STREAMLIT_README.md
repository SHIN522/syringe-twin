# SyringeTwin — Streamlit dashboard

A working local dashboard for Group 07’s syringe assembly simulation. The dashboard connects to a separate FastAPI backend over HTTP. MQTT and Mosquitto are not required. The backend keeps simulating independently of Streamlit refreshes and page changes.

## Start on Windows

1. Extract the ZIP completely, then open its `SyringeTwin_Streamlit` folder.
2. Double-click **Install_Windows.bat** once. It uses the `py` launcher you already have.
3. Double-click **Start_Windows.bat**. The browser opens automatically. Press **Start** in the dashboard.

Or run these commands in a terminal opened in that folder:

```powershell
py -m pip install -r requirements.txt
py launch.py
```

Open http://127.0.0.1:8501 if the browser does not open. Keep the terminal open; Ctrl+C closes both services.

## Start on macOS or Linux

Python 3.11 or later is required. This package was tested with Python 3.12.14 on Linux.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python launch.py
```

## What works

- Live overview of IN → S1 print/cure → S2 press/insertion → S3 cap/mark → S4 inspection → OUT packing.
- Ten unique pallets, four FIFO buffers, two-second transfers and ten-second empty pallet returns.
- Station state and SFC step display; buffer occupancy plus reservations; material stock levels.
- Loaded, good, rejected, WIP and cumulative box counters.
- Start, Stop, latched E-stop, alarm Reset, 1×/2×/5×/10×/50× simulation speeds.
- S2 wear, sampled press force, quality rejection, naturally occurring overload, injected F201, 90-second repair and 20-second planned tool change.
- Throughput, line cycle time, lead time, OEE, availability/performance/quality, reject codes and force trends.
- Per-serial measurements, inspection codes and process timeline; JSON export.
- Alarm history, operator command audit, recent events and CSV exports.
- SQLite historian under `data/`; each backend launch creates its own database so earlier runs are not overwritten.
- Reconnection every 0.5 seconds, disconnected-state display and engine-staleness detection.

All values come from the running Python model. There is no mock-data dashboard mode. The SVG refreshes at two frames per second; it is a live process overview rather than a smooth continuous animation.

## Quick demonstration

1. Keep 10× speed, enter your operator name, and press **Start**. Allow roughly 10 real seconds for the first good exits.
2. Open **Traceability** and select a recent serial to show its measurements and timeline.
3. Open **Maintenance**. Click **Inject F201** while S2 is RUNNING. The affected serial is explicitly marked `injected:true`.
4. Keep the line running. S2 faults locally; upstream buffers fill and downstream stations become starved.
5. Press **Repair S2**, wait 90 simulation seconds (about 9 real seconds at 10×), then **Reset alarms**. S2 resumes at RETRACT and the affected part is rejected for R2.
6. Demonstrate **EMERGENCY STOP → Release E-stop → Reset alarms → Start**.
7. Review **Alarms & audit** and **Trends**. Download the audit or trend CSV if needed.

If the fault button rejects the command, wait for an active S2 processing cycle. Reset alone cannot clear an unrepaired F201. Stop freezes process progress; the simulation clock still advances, so the rolling throughput window can decay while stopped. Bin refills and maintenance timers advance while the line is running.

## KPI interpretation

Throughput is good exits in the trailing 600 simulation seconds multiplied by six, matching the brief. It starts low during warm-up. OEE is measured at S2: A × P × Q, with a 10-second ideal cycle. It is a cumulative measure for the current run. Quality is measured at inspection decisions; good/reject output counters update when physical unloading/diversion completes. Small timing differences between those quantities are expected.

Null values appear as “—”. Prediction fits the last 30 force samples and can vary considerably while the sample count is low. Reject Pareto counts codes, so one rejected unit can contribute to multiple codes. Conservation badges check parts and unique pallets; Little’s Law is verified offline over a shared measurement window.

## Tests and evidence

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
PYTHONPATH=. python tests/ui_smoke.py
PYTHONPATH=. python tests/save_evidence.py
```

On Windows PowerShell, use `$env:PYTHONPATH = "."` before the last two commands, then run them using `py`.

Evidence and the validation record are in `docs/evidence/`. The UI smoke test starts its own backend on port 8012 and tests Start, all pages, E-stop recovery, F201 recovery, and disconnection through Streamlit’s AppTest framework. It does not require a browser driver.

## Scope and provenance

The prior simulation source could not be recovered from the available project files. This package reconstructs a dashboard MVP from `PROJECT_BRIEF-2.md` and `DECISIONS.md`; its tests and measured evidence are new. It does **not** inherit the earlier claim of 29 passing tests.

The engine uses explicit SFC sequence actions in `control.py`, separate timing/measurement physics in `plant.py`, and fixed 100 ms simulation steps. The complete frozen PLC I/O mapping, rung-linked P1–P9 implementation and OpenPLC diagrams remain unfinished. This package is not a substitute for a required PLC/CoppeliaSim/Webots deliverable. The report, PPT and simulation video are not included in this dashboard package.

Only F201 and the simulated global E-stop are implemented here. F101/F401, `set_param`, the what-if endpoint, persistent-state restart recovery and the custom browser frontend remain future work. Restarts begin a fresh simulation; past histories remain in their own SQLite files. Current dashboard traceability shows the current run.

## Custom browser dashboard next

The API already exposes `GET /api/live`, `/api/snapshot`, `/api/kpi`, `/api/parts`, `/api/parts/{serial}`, `/api/alarms`, `/api/commands` and `/api/events`, plus `POST /api/commands` with `{cmd,args,user}`. The existing snapshot/KPI keys follow the brief. Later we can replace only the Streamlit frontend and add WebSocket streaming, preserving the model, commands and historian.

## Troubleshooting

- **Port already in use:** close the earlier app, or use `py launch.py --api-port 8010 --ui-port 8510`.
- **Service unavailable:** use `launch.py`, which starts both services. Launching Streamlit alone will not start the backend.
- **Missing packages:** install with the same Python launcher used to launch the app.
- **Python 3.14 installation issues:** use Python 3.12 or 3.13 and the matching launcher, for example `py -3.12 -m pip install -r requirements.txt`, then `py -3.12 launch.py`.
- **Another machine:** this launcher deliberately binds to the local laptop. Hosting and remote access are not configured.

This MVP implements simulated controls, not hardware safety functions or medical-device compliance.
