@echo off
title Garrison Recorder Console
echo [recorder] Garrison Protocol passive recorder (console)
echo [recorder] data output: E:\garrison-ai\data\raw
set PY=E:\garrison-ai\venv\Scripts\python.exe
if not exist "%PY%" (
    echo [error] venv python not found: %PY%
    pause
    exit /b 1
)
echo [recorder] starting... play your game, press Ctrl+C here to stop.
"%PY%" "%~dp0capture.py" --record
echo [recorder] stopped.
pause