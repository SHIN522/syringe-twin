# Authorized dashboard change — 5 October 2026

The user requested a working Streamlit dashboard ASAP, with a custom browser dashboard to follow. This instruction overrides the original dashboard stack and MQTT transport recommendations for this interim version.

- Streamlit becomes the interim HMI.
- FastAPI remains a separate simulation service and supplies snapshot/KPI reads and validated commands over HTTP.
- Added endpoints: `/api/live`, `/api/snapshot`, `/api/kpi`, `/api/events` and POST `/api/commands`.
- Existing snapshot/KPI keys, command shape, maintained E-stop and F201 repair/reset semantics are retained.
- Streamlit, requests, pandas and Plotly are authorized implementation dependencies for the requested interface.
- Source is reconstructed from the recovered specification. Full PLC tag integration and documentation are not claimed complete.
- The browser dashboard can replace the Streamlit interface later without moving the simulation clock into the UI.

## Current Windows/browser extension — 5 October 2026

The current user requested Windows localhost setup, then a running simulation on a site, followed by a collaborative GitHub repository. This supersedes the archived Mac-first priority and authorizes the custom browser dashboard now.

- Preserve the original Streamlit fallback on localhost:8501. Serve the custom browser frontend on the FastAPI origin at localhost:8000.
- Add read-only station progress and pallet identity metadata to support interpolation; fixed-step timing, commands and engineering parameters are unchanged.
- A private static hosted site runs the identical bundled Python model in an isolated Pyodide worker. Each browser tab owns its simulation and memory history; it does not relay commands to the user's localhost or claim shared/server persistence.
- Background Windows startup uses the project virtual environment, logs and an instance-scoped stop request. Runtime state, environments and SQLite files are ignored by Git and excluded from delivery archives.
- Treat `shmizi` as the intended GitHub collaborator supplied by the user; record invitations only after GitHub confirms them.
