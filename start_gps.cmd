@echo off
rem One-click start for NWN GPS from source (recorder + in-game panel). Ctrl+C in this window stops both.
title NWN GPS
cd /d "%~dp0"
if not exist native\build\nwngps_gl.dll call native\build.cmd || (echo DLL build failed & pause & exit /b 1)
python -m nwngps
pause
