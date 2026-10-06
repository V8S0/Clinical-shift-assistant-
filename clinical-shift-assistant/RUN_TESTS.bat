@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_APP.bat first so the dependencies are installed.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q
pause
