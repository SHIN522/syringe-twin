#!/usr/bin/env bash
# One-time: install CoppeliaSim Edu 4.10 on Ubuntu 22.04/24.04 into ~/CoppeliaSim,
# so the PLC -> twin -> CoppeliaSim demo runs on the same machine as OpenPLC.
# Usage (from the repository folder):  bash tools/ubuntu_coppelia.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/CoppeliaSim"
. /etc/os-release
case "$VERSION_ID" in
  24.*) BUILD=Ubuntu24_04 ;;
  *)    BUILD=Ubuntu22_04 ;;
esac
NAME="CoppeliaSim_Edu_V4_10_0_rev0_${BUILD}"

echo "== 1/3 Libraries CoppeliaSim's Qt GUI needs"
sudo apt-get install -y xz-utils libxcb-cursor0 libxkbcommon-x11-0 libgl1 libglu1-mesa

echo "== 2/3 CoppeliaSim Edu ($BUILD, ~250 MB)"
if [ ! -x "$DEST/coppeliaSim.sh" ]; then
  curl -fL -o "/tmp/$NAME.tar.xz" "https://downloads.coppeliarobotics.com/V4_10_0_rev0/$NAME.tar.xz"
  tar -xJf "/tmp/$NAME.tar.xz" -C "$HOME"
  rm -rf "$DEST" && mv "$HOME/$NAME" "$DEST"
  rm "/tmp/$NAME.tar.xz"
fi

echo "== 3/3 Python client for the remote API"
"$REPO/.venv/bin/pip" install -r "$REPO/requirements.txt"

echo
echo "Installed: $DEST/coppeliaSim.sh"
echo "Demo steps: docs/plc/UBUNTU_RUNBOOK.md, section 7"
