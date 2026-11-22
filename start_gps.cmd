@echo off
rem Start NWN GPS from source (developers). Players: use NWN-GPS.exe from the release zip instead.
title NWN GPS
cd /d "%~dp0"
python -c "import PIL" 2>nul || (
  echo NWN GPS needs the Pillow package for this Python:  python -m pip install pillow
  echo ^(Or use the packaged dist\NWN-GPS\NWN-GPS.exe, which needs nothing installed.^)
  pause
  exit /b 1
)
if not exist native\build\nwngps_gl.dll call native\build.cmd || (echo DLL build failed & pause & exit /b 1)
python -m nwngps
pause
