@echo off
chcp 65001 >nul
title txrui 启动器

:: 检测是否首次运行或需要环境检查
if not exist "%~dp0.setup_complete" (
    echo ========================================
    echo      txrui 首次运行设置
    echo ========================================
    echo.
    echo 正在检查环境和解除文件阻止...
    echo.
    
    :: 运行 PowerShell 设置脚本
    powershell -ExecutionPolicy Bypass -File "%~dp0first_run_setup.ps1"
    
    if %errorlevel% equ 0 (
        :: 创建标记文件，表示已完成首次设置
        echo. > "%~dp0.setup_complete"
        echo.
        echo ✓ 首次设置完成
        echo.
    ) else (
        echo.
        echo ✗ 环境检查未通过，请查看上述错误信息
        echo.
        pause
        exit /b 1
    )
)

:: 启动 txrui
echo 正在启动 txrui...
start "" "%~dp0txrui.exe" %*

:: 可选：等待进程启动
timeout /t 2 /nobreak >nul

exit /b 0
