@echo off
REM Start Jarvis Voice Assistant (Windows)
REM Usage: run.bat            With desktop HUD
REM        run.bat --no-pet   Command-line only
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -u -m jarvis %*
