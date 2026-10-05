# SyringeTwin

An interactive digital twin of Group 07's syringe assembly cell: IN → printing/cure → press/insertion → cap/mark → inspection → packing. The animated browser dashboard and the retained Streamlit dashboard share one local Python engine. A hosted browser simulation runs the same bundled Python model independently in a Web Worker.

## Start on Windows

Python 3.11 or later is required. This working copy has a configured Python 3.12 virtual environment.

1. Double-click `Start_Windows.bat`. It opens the browser dashboard at **http://127.0.0.1:8000** and keeps both services running in the background.
2. Enter an operator name and press **Start**. The Streamlit dashboard is also available at **http://127.0.0.1:8501**.
3. Double-click `Stop_Windows.bat` to shut down both services. Dashboard **Stop** pauses production while retaining the running services and current parts.

For a freshly downloaded copy, `Install_Windows.bat` installs dependencies into `.venv`. Start also installs automatically if `.venv` does not exist. No global package installation or administrator privileges are needed.

PowerShell alternative, from this folder:

```powershell
py -3 tools/setup_env.py --dev
& .\.venv\Scripts\python.exe launch.py --background
& .\.venv\Scripts\python.exe launch.py --stop
```

For a console session use `launch.py` without `--background`; Ctrl+C closes both services. Logs for background sessions are in `.runtime/stdout.log` and `.runtime/stderr.log`. A second background launch reopens the existing session. To choose different ports, stop the current session first, then run `launch.py --background --api-port 8001 --ui-port 8502`.

## macOS and Linux

```bash
python3 tools/setup_env.py --dev
.venv/bin/python launch.py
```

Open http://127.0.0.1:8000; keep the terminal open, and use Ctrl+C to close. The current installation and launch flow were verified on Windows. Cross-platform CI is included; macOS device execution is not claimed.

## Demonstrate the cell

- Keep **10×** speed and press **Start**. The first outputs take roughly ten real seconds, depending on startup state. All durations refer to simulation seconds.
- Watch real serials move between six stations and four FIFO buffers. The engine owns process progress; the UI interpolates motion between snapshots.
- Open traceability to inspect a serial's measurements, decisions and events, then export JSON.
- Inject **F201** while S2 is processing. It holds S2 locally; upstream blocks and downstream starves. Press **Repair S2**, wait 90 simulation seconds, then **Reset**. The affected part retains its overload trace and receives R2 rejection.
- For E-stop use **Engage → Release → Reset → Start**. Reset while the physical E-stop is active cannot clear it.
- Planned tool change takes 20 simulation seconds at the next S2 WAIT boundary. Refills take 30 simulation seconds. Maintenance and refill timers advance while the line is running.

Natural wear and quality noise are enabled. A running line can develop an overload; it is not a dashboard connection failure. Stop freezes production progress while the simulation clock continues.

## Local and hosted behavior

| Mode | Simulation owner | History | Laptop required |
| --- | --- | --- | --- |
| Local browser dashboard | FastAPI background service | Per-run SQLite in `data/` | Yes |
| Local Streamlit | Same FastAPI service | Same local run | Yes |
| Hosted browser simulation | Python/Pyodide worker in each open tab | Memory and JSON exports | No |

The hosted site is initially private. It loads the pinned Pyodide runtime and NumPy/PyYAML from the official runtime CDN. Initial loading requires internet access. Closing/reloading a hosted tab starts a new independent run; it does not control or mirror the local laptop. For local testing of this mode use `http://127.0.0.1:8000/?engine=browser`.

The deployed private simulation is at [SyringeTwin Lab](https://syringetwin-lab.aryan-kapil-btech202.chatgpt.site).

Each backend restart begins a fresh simulation and creates a separate database. Earlier databases remain on disk; model state is not restored automatically.

## Measurements and boundaries

- Fixed 0.1-second steps, seed 7, per-station random generators, ten unique pallets, FIFO buffers and reserved two-second transfers.
- Design rate is **360 units/hour** with the ten-second line cycle. Default noisy/wearing production is not guaranteed to reach this rate.
- Throughput uses good exits in the trailing 600 simulation seconds multiplied by six. OEE is cumulative A × P × Q at S2. Quality uses inspection decisions; output counts update at unloading/diversion.
- Undefined measurements display **—**. Reject Pareto counts codes; a part can have multiple codes. Live Little's Law remains undefined; the original offline aligned-window baseline verifies it.
- This is a Python process/SFC demonstration. Full frozen PLC I/O/P1–P9 ladder integration and an external industrial simulator remain unfinished. The simulation does not establish medical-device or hardware validation.
- Local command audit and traceability are preserved. Very long, fast runs can accumulate substantial part/event history; restart creates a fresh run.

The original handoff and Streamlit ZIP contain identical project sources. Archived specification documents and prior Linux evidence are preserved separately from the current Windows evidence. The earlier Streamlit-only README is in `docs/ORIGINAL_STREAMLIT_README.md`.

## Development

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests
$env:PYTHONPATH = "."
& .\.venv\Scripts\python.exe tests/ui_smoke.py
& .\.venv\Scripts\python.exe tools/build_web.py
```

Regenerate `web/model_bundle.json` whenever model code or `config/line.yaml` changes. Tests verify that local and browser source/config are identical. `CONTRIBUTING.md`, `.github/workflows/ci.yml` and `docs/COLLABORATION.md` describe team changes and the intended `shmizi` collaboration. Do not commit `.venv`, `.runtime`, databases or credentials.

Current operational evidence is in `docs/evidence/windows_*` and `docs/evidence/OPERATIONAL_STATUS.md`; older evidence is labeled by its original files. GitHub publication and invitation status are recorded in the delivery status once completed.
