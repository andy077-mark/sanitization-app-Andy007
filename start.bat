@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python is required.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment is missing. Install the pinned dependencies first.
  echo Example: python -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
  pause
  exit /b 1
)

.venv\Scripts\python.exe main.py --serve
pause
