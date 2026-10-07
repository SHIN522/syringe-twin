# OpenPLC on Ubuntu: runbook

Everything runs on the same Ubuntu machine: OpenPLC Runtime v3 (the PLC) and the SyringeTwin service (the plant model, MES and dashboard). They talk over Modbus TCP on localhost:502.

## 0. Get the latest code

```bash
git clone https://github.com/SHIN522/syringe-twin.git && cd syringe-twin
```

If the repository is already on this machine, run `git pull` inside it instead.

## 1. One-time setup (about 20 minutes)

```bash
bash tools/ubuntu_setup.sh
```

It installs OpenPLC Runtime v3 into `~/OpenPLC_v3` and the twin's Python environment into `.venv`, then starts OpenPLC as the `openplc` systemd service, which also starts on every boot. No terminal needs to stay open:

```bash
sudo systemctl status openplc     # running?
sudo systemctl start openplc      # start it if not
sudo systemctl restart openplc    # restart it
```

Do not also run `start_openplc.sh` by hand while the service runs: the second copy fails because port 8080 is taken.

## 2. Configure OpenPLC (browser, about 3 minutes)

1. Open http://localhost:8080 and log in with `openplc` / `openplc`. **Users → change the password** immediately.
2. **Settings**: tick *Enable Modbus Server*, port **502**. Save.
3. **Programs → Upload Program** → `plc/openplc/spike.st` → *Upload Program* → wait for "Compilation finished successfully" → *Go to Dashboard* → **Start PLC**.

## 3. Connection test (go / no-go)

```bash
.venv/bin/python tools/plc_probe.py
```

It must end with `GO: OpenPLC path confirmed.`

## 4. Load the real program and run the PLC acceptance tests

1. **Programs → Upload Program** → `plc/openplc/syringetwin.st` → compile → **Start PLC**.
2. Run PLC-01…PLC-13 automatically (about 15 seconds):

   ```bash
   .venv/bin/python tools/plc_acceptance.py
   ```

   Results are saved to `docs/evidence/plc_manual_results.json`.
3. Regenerate the validation matrix so it includes the real-PLC rows:

   ```bash
   .venv/bin/python tools/validation_matrix.py
   ```

4. **Screenshot** OpenPLC's *Monitoring* page while the PLC runs. It is evidence for the report.

## 5. Run the twin under PLC control

The OpenPLC program must be running.

```bash
.venv/bin/python launch.py --plc 127.0.0.1 --profile demo --opcua
```

Open http://127.0.0.1:8000, enter an operator name, then:

1. Press **Reset alarms** once. At power-up the PLC sees the E-stop input as open before the twin's first write, so it latches F001; this is intended.
2. Press **Start line**. The blue *OpenPLC* strip shows the run permissive, PLC tower lamps and PLC counters.
3. Demo checks: E-stop → PLC latches F001 · natural F201 at ~87 s (10×) is decided by the PLC · Repair → Reset · **Stop PLC in the OpenPLC dashboard** → the twin halts with F002 within 1 s → Start PLC → Reset → Start.

Stop everything with Ctrl+C in the launch terminal.

## 6. Save the evidence

```bash
git add docs/evidence && git commit -m "Record OpenPLC acceptance results on Ubuntu" && git push
```

## 7. Live demo: OpenPLC → twin → CoppeliaSim + HMI (all on Ubuntu)

One-time, about 10 minutes: CoppeliaSim Edu 4.10 into `~/CoppeliaSim`, FUXA into `~/fuxa-hmi` (both outside the repository).

```bash
git pull && bash tools/ubuntu_coppelia.sh && bash tools/ubuntu_hmi.sh
```

Every demo:

1. Make sure OpenPLC is running (`sudo systemctl start openplc`; it normally starts on boot), open http://localhost:8080, **Start PLC** with `syringetwin.st`.
2. From the repository: `bash tools/ubuntu_demo.sh`. It starts the twin under PLC control (with OPC UA), the FUXA HMI (loading `hmi/syringetwin_hmi.json`), and the CoppeliaSim cell, and opens the dashboard and HMI. Ctrl+C stops all of it. Logs: `.runtime/demo/`.
3. Arrange the windows: CoppeliaSim, the dashboard (or FUXA HMI), and OpenPLC *Monitoring*.

In the dashboard (http://127.0.0.1:8000): **Reset alarms**, then **Start line**, speed 2×. What to point at:

| Action | PLC | CoppeliaSim |
|---|---|---|
| Start line | `M_SYS_RUN` true | PLC cabinet RUN LED green, pallets move, stack light green |
| Every S2 press | PLC decides F201 and returns the verdict sequence | S2 only releases the pallet after the PLC verdict |
| E-stop | PLC latches `F001` | everything freezes, panel E-stop blinks, stack light red |
| Natural F201 (~87 s at 10×) | PLC sets `F201` | S2 housing red, upstream blocks, downstream starves |
| **Stop PLC** in OpenPLC | Modbus stops answering | twin raises F002 within 1 s, line halts, cabinet LINK LED goes dark and FAULT blinks |
| Start PLC → Reset → Start | | line resumes |

The **Stop PLC** step is the proof that the PLC is in the loop: the 3D line cannot run without it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Setup script: "OpenPLC build failed" | Read the end of `~/OpenPLC_v3/install_log.txt`, install what is missing, rerun `bash tools/ubuntu_setup.sh`. |
| http://localhost:8080 does not load | `sudo systemctl status openplc`; `sudo journalctl -u openplc -n 50` shows why it stopped. |
| `plc_probe.py`: no Modbus server | Settings → Modbus enabled on 502, then **Start PLC** (Modbus only runs while the PLC runs). |
| Compile error on upload | Make sure the file is `syringetwin.st` from this repository; it is verified with the matiec compiler. |
| Port 8000 in use | `.venv/bin/python launch.py --stop`, or choose `--api-port 8001 --ui-port 8502`. |
| Twin shows F002 immediately | The PLC is stopped, or the program is `spike.st` instead of `syringetwin.st`. |
| CoppeliaSim on Ubuntu does not start | Run `QT_QPA_PLATFORM=xcb ~/CoppeliaSim/coppeliaSim.sh` in its own terminal to see the error; once it is open, run `.venv/bin/python tools/coppelia_view.py` (without `--launch`). |
