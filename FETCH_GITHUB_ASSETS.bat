@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo  Aion 2 Cube Finder - GitHub Source Sync
 echo ==========================================
echo This downloads PUBLIC repository files for offline review.
echo Files remain separate from the Cube Finder application.
echo No downloaded code is automatically executed.
echo.
py -3 sync_github_sources.py
if errorlevel 1 (
  echo.
  echo Download encountered an error. See messages above.
) else (
  echo.
  echo Finished. See the upstream_sources folder.
)
pause
