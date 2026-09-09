@echo off
setlocal
cd /d "%~dp0"

echo ======================================================================
echo  ZetaJarvis Enterprise Automation Node - Production Build Pipeline
echo ======================================================================

set PYTHON_EXE=.venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" build.py %*
if errorlevel 1 (
    echo [ERROR] Build pipeline failed!
    exit /b 1
)

echo [SUCCESS] ZetaJarvis built and packaged successfully!
exit /b 0
