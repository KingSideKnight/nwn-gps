@echo off
rem Build nwngps_gl.dll (x64) with Visual Studio 2022's compiler.
setlocal
set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat
call "%VCVARS%" >nul || exit /b 1
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /LD /O2 /W4 /wd4100 /wd4054 /wd4055 /wd4152 /Fo:build\ /Fe:build\nwngps_gl_new.dll nwngps_gl.c ^
   /link opengl32.lib user32.lib gdi32.lib kernel32.lib || exit /b 1
move /y build\nwngps_gl_new.dll build\nwngps_gl.dll >nul 2>&1 || echo note: build\nwngps_gl.dll is in use; fresh build is build\nwngps_gl_new.dll

