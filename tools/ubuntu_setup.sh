#!/usr/bin/env bash
# One-time Ubuntu setup: OpenPLC Runtime v3 + the SyringeTwin Python environment.
# Usage (from the repository folder):  bash tools/ubuntu_setup.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OPENPLC="$HOME/OpenPLC_v3"

echo "== 1/4 System packages"
sudo apt-get update
sudo apt-get install -y git curl build-essential python3 python3-venv python3-pip

echo "== 2/4 Python 3.11+ for the twin"
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    PY="$(command -v "$candidate")"; break
  fi
done
if [ -z "$PY" ]; then
  echo "System Python is older than 3.11; installing python3.11 from the deadsnakes PPA."
  sudo apt-get install -y software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update
  sudo apt-get install -y python3.11 python3.11-venv
  PY="$(command -v python3.11)"
fi
echo "Using $PY ($("$PY" --version))"

echo "== 3/4 OpenPLC Runtime v3 (compiles for ~10-15 minutes the first time)"
if [ ! -d "$OPENPLC" ]; then
  git clone --depth 1 https://github.com/thiagoralves/OpenPLC_v3.git "$OPENPLC"
fi
(cd "$OPENPLC" && ./install.sh linux)

echo "== 4/4 SyringeTwin environment"
(cd "$REPO" && "$PY" tools/setup_env.py --dev)

echo
if curl -fsS -o /dev/null http://localhost:8080/login; then
  echo "OpenPLC is running: open http://localhost:8080"
else
  echo "Start OpenPLC in its own terminal:  cd $OPENPLC && sudo ./start_openplc.sh"
  echo "then open http://localhost:8080"
fi
echo "Next steps: docs/plc/UBUNTU_RUNBOOK.md"
