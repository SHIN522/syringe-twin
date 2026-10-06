# Delivery status — 6 October 2026

The local setup is installed and running on the user's Windows machine. Browser simulation: http://127.0.0.1:8000 ; retained Streamlit: http://127.0.0.1:8501 . Use Start_Windows.bat and Stop_Windows.bat for the managed background session.

The private hosted simulation deployed successfully at:

https://syringetwin-lab.aryan-kapil-btech202.chatgpt.site

The hosted tab runs an independent instance of the same bundled Python model. It remains usable without a running laptop but downloads the pinned runtime at initial loading. It begins stopped; enter an operator name and press Start.

Validation: 23 Windows pytest tests, 11 Streamlit interface checks, browser Python/WASM startup and actual production, E-stop recovery, injected F201 repair/reset, and exported affected-part trace with injection and R2 retained. Evidence is in docs/evidence/windows_* and browser_validation.json. Narrow phone viewport verification remains unconfirmed because the in-app viewport override did not apply.

Site identity: appgprj_6ac3e787ab708191afb443d584da7363

Source commit: 0a40c9bc0a256fd7d734ad96b1acd1a6a80a68ff

Saved version: appgprj_6ac3e787ab708191afb443d584da7363~appgver_2603275027dc81919af2e604edb632ac

Deployment: appgdep_6ac3ed8ce954819184a46d58f4a7f57d — succeeded

The supported source helper pushed and verified the exact source. Its Bash packaging step did not work with Windows directory permissions/path handling; a standard-library fallback packaged only the exact committed static assets and validated archive contents. The native Sites deployment confirmed success.

GitHub repository: https://github.com/SHIN522/syringe-twin — private, owned by SHIN522. GitHub CLI sign-in is complete. The repository includes the source, contribution guide, issue/PR templates and Windows/Ubuntu CI. A write-access invitation was sent to shmizi (invitation ID 336275351); access becomes active after acceptance. The local checkout uses this repository as origin.

Engineering limitations remain as described in README and OPERATIONAL_STATUS: this is the supplied Python SFC model, with no claim of full PLC ladder/I/O, external simulator integration, hardware/medical validation or model-state restoration across restarts.
