@echo off
setlocal
cd /d "%~dp0"
python build_exe.py
if errorlevel 1 (
    echo Build failed. Install requirements-build.txt and try again.
    pause
    exit /b 1
)
echo Output: %~dp0dist\txrui\txrui.exe
pause
