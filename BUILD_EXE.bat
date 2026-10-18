@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run INSTALL.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name "Aion2CubeFinder-v17" ^
  --collect-all PySide6 --collect-all soundcard --collect-all mss --collect-all cv2 ^
  --hidden-import scapy.arch.windows --add-data "assets;assets" ^
  --icon "assets\cube_finder.ico" cube_finder_modern.py
if errorlevel 1 goto :fail
echo.
echo Completed: dist\Aion2CubeFinder-v17\Aion2CubeFinder-v17.exe
pause
exit /b 0
:fail
echo EXE build failed; review the output above.
pause
exit /b 1
