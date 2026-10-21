@echo off
rem ============================================================
rem  LVGL Console UI - Simulator  (double-click to start)
rem
rem  Runs serve.py (Python), opens the browser, keeps the
rem  console window open. Close the window or Ctrl+C to stop.
rem
rem  NOTE: keep this file ASCII-only. cmd.exe reads .bat in the
rem  system codepage (CP950 here), so UTF-8 Chinese in a .bat
rem  becomes garbage and the lines break apart.
rem ============================================================
setlocal
cd /d "%~dp0"

rem console must be UTF-8 to match Python output (see serve.py stdout.reconfigure)
chcp 65001 >nul

set "PY=python"
where python >nul 2>nul || set "PY=py -3"

echo.
echo   LVGL Console UI  ^>  http://127.0.0.1:8610/
echo   (close this window or press Ctrl+C to stop)
echo.

%PY% "%~dp0serve.py" %*

if errorlevel 1 (
  echo.
  echo   [ERROR] Could not start. Is Python 3.8+ installed?
  echo           https://www.python.org/downloads/
  echo.
  pause
)
