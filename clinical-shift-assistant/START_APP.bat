@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo AI Clinical Shift Assistant - One Click Start
echo ============================================

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher "py" was not found.
  echo Install Python 3.11 or newer, then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating virtual environment...
  py -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo [1/4] Virtual environment already exists.
)

echo [2/4] Installing required packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Starting backend at http://127.0.0.1:8000 ...
start "Clinical Assistant Backend" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe -m uvicorn backend.main:app --reload"

timeout /t 3 /nobreak >nul

echo [4/4] Starting frontend at http://127.0.0.1:5500 ...
start "Clinical Assistant Frontend" cmd /k "cd /d "%~dp0frontend" && ..\.venv\Scripts\python.exe -m http.server 5500"

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5500/index.html"

echo.
echo Application started.
echo Login: nurse
echo Password: Nurse123!
echo.
echo Keep both server windows open while using the application.
pause
exit /b 0

:failed
echo.
echo SETUP FAILED. Read the error above.
pause
exit /b 1
