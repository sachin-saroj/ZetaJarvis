@echo off
REM Quick Start Script for ZetaJarvis (Windows)
REM ===========================================

echo.
echo ========================================
echo    ZetaJarvis - Windows Edition
echo ========================================
echo.

REM Check if .env exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and configure it.
    pause
    exit /b 1
)

REM Check for API key
findstr /C:"JARVIS_API_KEY=your-" .env >nul
if %errorlevel% equ 0 (
    echo [WARNING] API key not configured!
    echo Please edit .env file and set your actual API key:
    echo   JARVIS_API_KEY=sk-your-actual-key
    echo.
    pause
)

echo [INFO] Starting ZetaJarvis...
echo.
echo TIPS:
echo   1. Close any background videos/music
echo   2. Wait for "Ready" message
echo   3. Say "Jarvis" or "Alpha" to wake
echo   4. Speak clearly in English/Hindi
echo   5. Press Ctrl+C to stop
echo.
echo ========================================
echo.

REM Start Jarvis
.venv\Scripts\python.exe -m jarvis --no-pet

echo.
echo ========================================
echo ZetaJarvis stopped.
echo ========================================
pause
