@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.bat first.
  pause
  exit /b 1
)
powershell -NoProfile -Command "Start-Process -FilePath '%CD%\.venv\Scripts\python.exe' -ArgumentList 'cube_finder_modern.py' -WorkingDirectory '%CD%' -Verb RunAs"
if errorlevel 1 pause
