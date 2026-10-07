#!/usr/bin/env bash
# One-time: install the FUXA operator HMI on Ubuntu into ~/fuxa-hmi (outside the repository).
# Usage (from the repository folder):  bash tools/ubuntu_hmi.sh
set -euo pipefail
DEST="$HOME/fuxa-hmi"

echo "== 1/3 Node.js 20 (Ubuntu's own nodejs package is too old for FUXA)"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
node --version

echo "== 2/3 FUXA 1.3.4 and its OPC UA plugin"
mkdir -p "$DEST"
cd "$DEST"
[ -f package.json ] || npm init -y >/dev/null
npm install @frangoteam/fuxa@1.3.4
npm install --prefix node_modules/@frangoteam/fuxa/_pkg node-opcua@2.149.0

echo "== 3/3 Done"
echo "FUXA is started by tools/ubuntu_demo.sh, which also loads hmi/syringetwin_hmi.json."
