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

It installs OpenPLC Runtime v3 into `~/OpenPLC_v3` and the twin's Python environment into `.venv`. If the script's last lines say OpenPLC is not running, start it in a separate terminal and leave that terminal open:

```bash
cd ~/OpenPLC_v3 && sudo ./start_openplc.sh
```

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

## Troubleshooting

| Symptom | Fix |
|---|---|
| `plc_probe.py`: no Modbus server | Settings → Modbus enabled on 502, then **Start PLC** (Modbus only runs while the PLC runs). |
| Compile error on upload | Make sure the file is `syringetwin.st` from this repository; it is verified with the matiec compiler. |
| Port 8000 in use | `.venv/bin/python launch.py --stop`, or choose `--api-port 8001 --ui-port 8502`. |
| Twin shows F002 immediately | The PLC is stopped, or the program is `spike.st` instead of `syringetwin.st`. |
