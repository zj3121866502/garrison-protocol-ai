@echo off
setlocal
title Garrison Advisor GUI
echo [run_gui] Garrison Protocol rest-phase decision assistant
echo [run_gui] Resolving paths...

set "PY=E:\garrison-ai\venv\Scripts\python.exe"
set "GUI=%~dp0advisor_gui.py"

if not exist "%PY%" (
  echo [run_gui] ERROR: venv python not found at "%PY%"
  echo [run_gui] Check that E:\garrison-ai\venv exists.
  pause
  exit /b 1
)
if not exist "%GUI%" (
  echo [run_gui] ERROR: advisor_gui.py not found next to this bat.
  pause
  exit /b 1
)

echo [run_gui] Python: %PY%
echo [run_gui] GUI:    %GUI%
echo [run_gui] Launching GUI window (always-on-top, display only, zero injection).
echo [run_gui] Set difficulty once in the dropdown, then play your solo game.
echo [run_gui] Keep this console open to see errors. Close the GUI to exit.
"%PY%" "%GUI%"
echo [run_gui] GUI exited with code %errorlevel%.
pause
endlocal