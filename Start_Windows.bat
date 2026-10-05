@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 tools\setup_env.py
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" launch.py --background
if errorlevel 1 pause
