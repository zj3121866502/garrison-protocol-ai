@echo off
setlocal
title Garrison Trial Run
echo [trial] Garrison Protocol trial-run launcher (form A rest-phase advisor)
echo [trial] Resolving paths...

set "PY=E:\garrison-ai\venv\Scripts\python.exe"
set "ROOT=%~dp0"
set "WATCHER=%ROOT%analysis\live_advisor.py"
set "GUI=%ROOT%ui\advisor_gui.py"

if not exist "%PY%" (
  echo [trial] ERROR: venv python not found at "%PY%"
  echo [trial] Check that E:\garrison-ai\venv exists.
  pause
  exit /b 1
)
if not exist "%WATCHER%" (
  echo [trial] ERROR: watcher not found at "%WATCHER%"
  pause
  exit /b 1
)
if not exist "%GUI%" (
  echo [trial] ERROR: advisor GUI not found at "%GUI%"
  pause
  exit /b 1
)

echo [trial] Python:  %PY%
echo [trial] Watcher: %WATCHER%
echo [trial] GUI:     %GUI%
echo [trial] ----------------------------------------------------------
echo [trial] BEFORE playing: start your passive recording bat FIRST.
echo [trial] Recording is user-started only. This launcher just READS
echo [trial] recorded frames. ZERO input injection. Bot never co-op.
echo [trial] Play a SOLO game manually; the corner window shows normal
echo [trial] play recommendations each rest phase. Rate them 1-10 there.
echo [trial] ----------------------------------------------------------
echo [trial] Starting watcher (minimized window, tails latest session)...
start "Garrison Watcher" /min "%PY%" "%WATCHER%"
echo [trial] Starting advisor GUI window (always-on-top, display only)...
echo [trial] Set difficulty once in the dropdown, then play.
echo [trial] Keep consoles open to see errors. Close GUI to exit.
"%PY%" "%GUI%"
echo [trial] GUI exited with code %errorlevel%.
echo [trial] Watcher may still run in its minimized window; close it to stop.
pause
endlocal