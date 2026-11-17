@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem 构建目录版 EXE。默认执行完整资源检查和成品自检；使用 --no-pause 适合 CI。
set "TXRUI_NO_PAUSE="
if /i "%~1"=="--no-pause" (
    set "TXRUI_NO_PAUSE=1"
    shift
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "TXRUI_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto build
)
if exist "%~dp0venv\Scripts\python.exe" (
    set "TXRUI_PYTHON=%~dp0venv\Scripts\python.exe"
    goto build
)
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install 64-bit Python 3.12 and requirements-build.txt first.
    set "TXRUI_EXIT_CODE=1"
    goto finish
)
set "TXRUI_PYTHON=python"
:build
set "PYTHONUTF8=1"
"%TXRUI_PYTHON%" "%~dp0build_exe.py" %*
set "TXRUI_EXIT_CODE=%ERRORLEVEL%"
if not "%TXRUI_EXIT_CODE%"=="0" (
    echo Build failed. Review the error above. The previous build is preserved.
) else (
    echo Output: %~dp0dist\txrui\txrui.exe
    echo Distribute the entire dist\txrui directory, not only txrui.exe.
)
:finish
if not defined TXRUI_NO_PAUSE pause
exit /b %TXRUI_EXIT_CODE%
