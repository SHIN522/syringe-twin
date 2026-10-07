# Operator HMI (FUXA)

`syringetwin_hmi.json` is a [FUXA](https://github.com/frangoteam/FUXA) project: one 1280 × 800 operator screen for Line 1.

| Area | Content |
|---|---|
| Header | Line state, simulation time, speed, stack light |
| Process overview | Six stations with state lamp and text, current SFC step, cycle count; B1–B4 buffer fill |
| Production | Good, reject, loaded, boxes, WIP, throughput, yield, rolling OEE, lead time |
| S2 press | Force with bar and 140/160 N limits, tool health, cycles to overload, Tool OK, tool change queued, maintenance time left |
| Alarms & inspection | F001, F201, W202, F002 lamps; last inspected serial with PASS/FAIL lamp and reject codes |
| Commands | Start, Stop, Reset, Repair S2, Tool change S2, Inject F201, Emergency stop, Release E-stop, speed 1×/2×/5×/10×, last command result |

**Connection.** FUXA is an OPC UA client of the twin (`opc.tcp://127.0.0.1:4840/syringetwin/`). It reads `Line1.*` nodes (IDs in `docs/plc/tag_dictionary.csv`) and writes only the `Line1.HMI.*` command nodes. The twin runs each write through the same validated command path as the dashboard, records it in the audit trail as user **HMI (OPC UA)**, clears the command bit and publishes the outcome in `Line1.HMI.LastResult`. Refused commands (for example Start during an E-stop) show the reason there.

**Run it.**
1. Start the twin with OPC UA: `.venv/Scripts/python.exe launch.py --profile demo --opcua`
2. Install FUXA 1.3.4 once (`npm install @frangoteam/fuxa@1.3.4`) and its OPC UA plugin (`npm install --prefix node_modules/@frangoteam/fuxa/_pkg node-opcua@2.149.0`), then start it: `node node_modules/@frangoteam/fuxa/main.js`
3. Open http://127.0.0.1:1881. To load this screen on a new FUXA installation: Editor → Project → Open project → `syringetwin_hmi.json`.

In PLC mode (`--plc`) the same screen still works: run, E-stop and F201 commands are forwarded by the twin to OpenPLC.

**On Ubuntu** `bash tools/ubuntu_hmi.sh` installs FUXA once, and `bash tools/ubuntu_demo.sh` starts it with this project loaded (see `docs/plc/UBUNTU_RUNBOOK.md`, section 7).
