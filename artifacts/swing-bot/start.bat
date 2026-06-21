@echo off
title STRUCT.ai Swing Engine
color 06
chcp 65001 >nul 2>&1

echo.
echo  =========================================================
echo   STRUCT.ai Swing Engine
echo   Entry: 1H  ^|  Structure: 4H  ^|  Bias: D1
echo  =========================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo.
    echo  Please install Python from https://python.org
    echo  IMPORTANT: During install, tick "Add Python to PATH"
    echo.
    pause
    goto :eof
)

echo  [OK] Python found.

:: Install dependencies
echo  [..] Installing dependencies...
pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install dependencies.
    pause
    goto :eof
)
echo  [OK] Dependencies ready.
echo.
echo  [..] Starting dashboard on http://localhost:5004
echo  Open your browser and go to: http://localhost:5004
echo  Press CTRL+C to stop the engine.
echo.

:: Open browser after 2 seconds
start "" /b cmd /c "timeout /t 2 >nul && start http://localhost:5004"

:: Start engine
python dashboard_server.py

echo.
echo  [STOPPED] Engine has stopped.
echo.
pause
