# Contributing to SyringeTwin

Use Python 3.11 or newer. Run these commands from the repository root.

## Windows setup

```powershell
py -3.11 tools/setup_env.py --dev
.\.venv\Scripts\python.exe launch.py --background
```

The setup script creates `.venv`, installs `requirements-dev.txt`, and builds the browser model bundle. Open the simulation at <http://127.0.0.1:8000> and Streamlit at <http://127.0.0.1:8501>. Both local dashboards control the same backend. Stop the managed session with:

```powershell
.\.venv\Scripts\python.exe launch.py --stop
```

## macOS and Linux setup

```bash
python3 tools/setup_env.py --dev
.venv/bin/python launch.py
```

Keep the terminal open while working; press Ctrl+C to stop both services. The same localhost URLs apply. Use `--api-port` and `--ui-port` on the launcher if either default port is occupied.

## Validate a change

Windows:

```powershell
.\.venv\Scripts\python.exe tools/build_web.py
.\.venv\Scripts\python.exe -m pytest tests
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe tests/ui_smoke.py
```

macOS/Linux:

```bash
.venv/bin/python tools/build_web.py
.venv/bin/python -m pytest tests
PYTHONPATH=. .venv/bin/python tests/ui_smoke.py
```

Rebuild and commit `web/model_bundle.json` whenever the model files or `config/line.yaml` change. The build script lists the model files included in the hosted simulation. `ui_smoke.py` starts its own temporary backend on port 8012; that port must be free. It checks live dashboard actions, alarms, recovery, traceability pages, and the disconnected state.

For browser changes, also run `node --check` on the changed JavaScript files with Node.js 24 and try the simulation in a browser. Check Start, Pause, E-stop/recovery, a station fault, and the displayed part counts. CI checks JavaScript syntax; it does not replace this browser interaction check.

## Pull requests

Create a short branch such as `feature/station-visuals`, `fix/alarm-reset`, or `docs/setup`. Keep each PR focused on one behavior. Explain the problem, resulting behavior, and the validation performed. Add a screenshot for visible dashboard changes.

Preserve the fixed-step model, deterministic seed behavior, serial traceability, part conservation, and fault/recovery semantics when changing the engine. Add a regression test when changing these behaviors. Keep dependencies in the requirements files and install into `.venv`.

Keep generated runtime history, `.venv`, `.runtime`, credentials, and local logs out of commits. Runtime history lives in `data/`; the browser model bundle is a versioned deliverable.

This project demonstrates a Python SFC simulation. External PLC integration and medical hardware operation are outside its current implementation. See [collaboration setup](docs/COLLABORATION.md) for the planned GitHub workflow.
