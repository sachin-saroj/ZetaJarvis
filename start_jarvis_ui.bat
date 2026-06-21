@echo off
REM Start ZetaJarvis with Full Holographic HUD UI
REM ============================================

echo.
echo ================================================
echo    ZetaJarvis - Iron Man Style HUD Edition
echo ================================================
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

echo [INFO] Starting ZetaJarvis with GUI...
echo.
echo FEATURES:
echo   - Iron Man style holographic HUD
echo   - Arc reactor (changes color with state)
echo   - Real-time system telemetry
echo   - Audio waveform visualization
echo   - Click reactor to talk (no wake word needed)
echo   - Double-click or ESC to close
echo.
echo TIPS:
echo   1. Close background videos/music
echo   2. Click the arc reactor to start talking
echo   3. Or say "Jarvis" to wake
echo   4. Drag anywhere to move window
echo   5. Press ESC or double-click to exit
echo.
echo ================================================
echo.

REM Start Jarvis WITH GUI (no --no-pet flag)
.venv\Scripts\python.exe -m jarvis

echo.
echo ================================================
echo ZetaJarvis HUD closed.
echo ================================================
pause
