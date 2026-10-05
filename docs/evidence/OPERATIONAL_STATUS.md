# Current operational status

Checkpoint: 5 October 2026, Asia/Kolkata. This records work on the user's Windows system, separately from the supplied Linux evidence.

- Both input archives opened safely. All 56 handoff manifest records match their supplied SHA-256 checksums; the 41 project files in the two archives are identical.
- Created a project-local Python 3.12.14 environment and installed the supplied pinned dependencies. `pip check` reports no broken requirements.
- FastAPI at `127.0.0.1:8000`, Streamlit at `127.0.0.1:8501`, and the browser entrypoint return HTTP 200. Backend health reports no engine error.
- Verified background launch, repeated start reusing the same managed session, clean requested stop, and restart on the same ports. Runtime instance checks avoid stopping a different app using that port.
- Existing Streamlit AppTest smoke execution on Windows passed all 11 checks: initial render, production Start, four additional workspaces, E-stop engagement/recovery, local F201 injection/repair/reset and backend disconnection feedback. Actual output is in `windows_ui_smoke.json`.
- Added API/animation metadata tests and browser/local model bundle consistency, with a parsed Kolkata timezone. Actual pytest output files record the completed suite.
- Browser visual/control verification and Site deployment are recorded in the final delivery status after those steps complete. GitHub CI definitions are prepared; they have not yet run on a remote repository.

Preserved model timing, per-station seeded randomness, ten pallets, FIFO/reservation semantics and audit commands. Added read-only metadata and a second frontend; hosted tabs use an independent instance of the same model.

Remaining model scope: complete PLC I/O/P1–P9 ladder-faithful scan, external PLC/industrial simulator integration, live Little's Law value, model restart restoration and previously deferred F101/F401/what-if work. Long runs accumulate histories and can need profiling. No hardware, medical validation, submission acceptance or Mac device execution is claimed.
