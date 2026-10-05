@echo off
cd /d "%~dp0"
py -3 tools\setup_env.py
if errorlevel 1 pause
