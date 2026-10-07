#!/usr/bin/env bash
# Start the whole demo on Ubuntu: twin (under OpenPLC control) + CoppeliaSim 3D cell + FUXA HMI.
# OpenPLC must already be running syringetwin.st (docs/plc/UBUNTU_RUNBOOK.md, section 4).
# Usage (from the repository folder):  bash tools/ubuntu_demo.sh          (with OpenPLC)
#                                      bash tools/ubuntu_demo.sh --no-plc (twin's internal logic)
# Ctrl+C stops everything this script started.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
FUXA="$HOME/fuxa-hmi/node_modules/@frangoteam/fuxa/main.js"
LOGS="$REPO/.runtime/demo"
mkdir -p "$LOGS"
PLC_ARGS=(--plc 127.0.0.1)
[ "${1:-}" = "--no-plc" ] && PLC_ARGS=()

pids=()
cleanup() {
  echo; echo "Stopping the demo..."
  "$PY" "$REPO/launch.py" --stop >/dev/null 2>&1  # lets launch.py close the twin and Streamlit itself
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null; done
}
trap cleanup EXIT INT TERM

wait_for() {  # url, name
  for _ in $(seq 1 60); do curl -fs -o /dev/null "$1" && return 0; sleep 1; done
  echo "$2 did not come up; see $LOGS"; exit 1
}

if [ ${#PLC_ARGS[@]} -gt 0 ] && ! (exec 3<>/dev/tcp/127.0.0.1/502) 2>/dev/null; then
  echo "OpenPLC's Modbus server is not answering on port 502."
  echo "Start OpenPLC (sudo systemctl start openplc), open http://localhost:8080, Start PLC with syringetwin.st, then rerun."
  echo "Or run without the PLC:  bash tools/ubuntu_demo.sh --no-plc"
  exit 1
fi

echo "== Twin (dashboard http://127.0.0.1:8000, OPC UA on 4840)"
"$PY" "$REPO/launch.py" "${PLC_ARGS[@]}" --profile demo --opcua --no-browser >"$LOGS/twin.log" 2>&1 &
pids+=($!)
wait_for http://127.0.0.1:8000/api/health "The twin"

if [ -f "$FUXA" ]; then
  echo "== FUXA HMI (http://127.0.0.1:1881)"
  (cd "$HOME/fuxa-hmi" && exec node "$FUXA") >"$LOGS/fuxa.log" 2>&1 &
  pids+=($!)
  wait_for http://127.0.0.1:1881 "FUXA"
  curl -fsS -X POST -H 'Content-Type: application/json' \
       --data-binary @"$REPO/hmi/syringetwin_hmi.json" http://127.0.0.1:1881/api/project >/dev/null \
    && echo "   HMI project loaded" || echo "   Could not load the HMI project; open it in FUXA's editor"
else
  echo "== FUXA not installed (bash tools/ubuntu_hmi.sh); skipping the HMI"
fi

echo "== CoppeliaSim 3D cell"
# CoppeliaSim's Qt build is most reliable on X11; under Wayland this runs it through XWayland.
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}" "$PY" "$REPO/tools/coppelia_view.py" --launch >"$LOGS/coppelia.log" 2>&1 &
pids+=($!)
sleep 2
kill -0 "${pids[-1]}" 2>/dev/null || echo "   3D view did not start: $(tail -n 1 "$LOGS/coppelia.log")"

xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 || true
[ -f "$FUXA" ] && (xdg-open http://127.0.0.1:1881 >/dev/null 2>&1 || true)
echo
echo "Running. Dashboard: Reset alarms, then Start line. OpenPLC: http://localhost:8080"
echo "Logs: $LOGS    Ctrl+C to stop everything."
wait
