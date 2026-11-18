@echo off
title Garrison Recorder GUI
echo [recorder] Garrison Protocol passive recorder (GUI)
echo [recorder] data output: E:\garrison-ai\data\raw
set PY=E:\garrison-ai\venv\Scripts\python.exe
if not exist "%PY%" (
    echo [error] venv python not found: %PY%
    pause
    exit /b 1
)
echo [recorder] starting GUI... click Start in the window, F9 stops recording.
"%PY%" "%~dp0recorder_gui.py"
echo [recorder] stopped.
pause