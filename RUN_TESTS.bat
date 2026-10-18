@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run INSTALL.bat to create Python 3.12 environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 (
  echo Some tests FAILED. Copy the output or take a screenshot.
) else (
  echo All offline tests passed. Live gameplay test still required.
)
pause
