@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run INSTALL.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" cube_finder_modern.py
if errorlevel 1 (
  echo.
  echo Startup error. Copy the error above and send it for troubleshooting.
  pause
)
