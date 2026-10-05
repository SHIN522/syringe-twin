# Validation record — 5 October 2026

This evidence applies to the newly reconstructed Streamlit dashboard package. It does not verify the earlier unavailable source.

| Check | Result |
|---|---|
| Automated model/API/SVG tests | 19 passed |
| Streamlit AppTest interface checks | 11 passed |
| One-command launcher starts both backend and Streamlit | Passed |
| Actual HTTP commands generate simulation serials | Passed |
| Part conservation every tick | Passed |
| Ten unique pallets across slots, buffers, transit and return | Passed |
| Maintained E-stop release → reset → start through UI | Passed |
| Local F201 inject → repair → wait → reset through UI | Passed |
| Disconnected interface state | Passed |
| Rate after 300-second warm-up, over 3,600-second window | 360 good units |
| Little’s Law using the same population/window | Error below 0.1% |
| Mean WIP and all-completion lead in measured baseline | 8.99 units; 89.9 seconds |
| SVG process overview render | Rendered and visually inspected |

The design-rate baseline disables wear and quality noise and keeps automatic material refill enabled. The default demo retains seed 7, initial wear 0.3, wear growth and quality noise; its production results differ from the baseline. See `baseline_measurements.json` for exact data and runtime.

AppTest exercises the actual Streamlit script with a real FastAPI process. It verifies page execution and control effects; it is not a browser pixel/screenshot test. A browser driver download failed in this environment, so the complete page has not been visually inspected in a real browser. The standalone process overview was rendered and inspected.

The full frozen PLC I/O/rung implementation, OpenPLC diagrams, external simulator integration, original submission report/PPT/video, what-if sandbox and custom browser dashboard remain outside this interim package.

Evidence files:

- `pytest_output.txt` — automated test output.
- `ui_checks.json` — eleven successful interface checks.
- `launcher_check.json` — both service health endpoints and serial generation.
- `baseline_measurements.json` — newly measured baseline values.
- `demo_snapshot.json` — real default-model snapshot at 200 simulated seconds.
- `cell_overview.svg` / `cell_overview.png` — overview rendered from that snapshot, not a full dashboard screenshot.
