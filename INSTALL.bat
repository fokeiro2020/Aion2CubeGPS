@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo Python 3.12 is required. Install it and try again.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
echo Installation complete. Run START.bat to launch Cube Finder.
pause
exit /b 0
:error
echo Installation failed. Review the error above.
pause
exit /b 1
