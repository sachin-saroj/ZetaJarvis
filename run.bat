@echo off
setlocal
cd /d "%~dp0"

echo ======================================================================
echo  Starting ZetaJarvis Enterprise Digital Worker Node...
echo ======================================================================

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" run.py %*

echo.
echo ======================================================================
echo  ZetaJarvis stopped.
echo ======================================================================
pause
