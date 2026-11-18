# txrui 首次运行设置脚本
# 自动解除文件阻止并验证环境

param(
    [Parameter(Mandatory=$false)]
    [switch]$Silent = $false  # 静默模式，不等待用户按键
)

$ErrorActionPreference = "Continue"

function Write-ColorHost {
    param(
        [string]$Message,
        [string]$Color = "White",
        [switch]$NoNewline
    )
    if (-not $Silent) {
        if ($NoNewline) {
            Write-Host $Message -ForegroundColor $Color -NoNewline
        } else {
            Write-Host $Message -ForegroundColor $Color
        }
    }
}

# 获取脚本所在目录
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) {
    $scriptDir = Get-Location
}

Write-ColorHost ""
Write-ColorHost "=======================================" -Color Cyan
Write-ColorHost "    txrui 首次运行环境设置" -Color Cyan
Write-ColorHost "=======================================" -Color Cyan
Write-ColorHost ""

# 1. 检测是否需要解除阻止
Write-ColorHost "[1/4] 检查文件阻止状态..." -Color Yellow

$blockedFiles = Get-ChildItem -Path $scriptDir -Recurse -Include "*.dll","*.exe","*.pyd" -ErrorAction SilentlyContinue | 
    Where-Object { 
        try {
            $null -ne (Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue)
        } catch {
            $false
        }
    }

if ($blockedFiles) {
    Write-ColorHost "   发现 $($blockedFiles.Count) 个被阻止的文件" -Color Yellow
    Write-ColorHost "   正在解除阻止..." -Color Yellow
    
    $unblockCount = 0
    foreach ($file in $blockedFiles) {
        try {
            Unblock-File -Path $file.FullName -ErrorAction Stop
            $unblockCount++
        } catch {
            Write-ColorHost "   警告: 无法解除阻止 $($file.Name)" -Color Red
        }
    }
    
    Write-ColorHost "   ✓ 已解除 $unblockCount 个文件的阻止" -Color Green
} else {
    Write-ColorHost "   ✓ 所有文件正常，无需解除阻止" -Color Green
}

Write-ColorHost ""

# 2. 检查 .NET Framework
Write-ColorHost "[2/4] 检查 .NET Framework..." -Color Yellow

$netVersionOK = $false
try {
    $release = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\' -ErrorAction Stop).Release
    if ($release -ge 394802) {  # .NET 4.6.2 或更高
        $netVersionOK = $true
        Write-ColorHost "   ✓ .NET Framework 版本正常 (Release: $release)" -Color Green
    } else {
        Write-ColorHost "   ✗ .NET Framework 版本过低 (需要 4.6.2+)" -Color Red
    }
} catch {
    Write-ColorHost "   ✗ 未检测到 .NET Framework 4.x" -Color Red
}

if (-not $netVersionOK) {
    Write-ColorHost ""
    Write-ColorHost "   请安装 .NET Framework 4.8:" -Color Yellow
    Write-ColorHost "   https://dotnet.microsoft.com/download/dotnet-framework/net48" -Color Cyan
}

Write-ColorHost ""

# 3. 检查关键 DLL
Write-ColorHost "[3/4] 检查关键文件..." -Color Yellow

$criticalFiles = @(
    "_internal\pythonnet\runtime\Python.Runtime.dll",
    "txrui.exe"
)

$allFilesOK = $true
foreach ($file in $criticalFiles) {
    $filePath = Join-Path $scriptDir $file
    if (Test-Path $filePath) {
        Write-ColorHost "   ✓ $file" -Color Green
    } else {
        Write-ColorHost "   ✗ $file (缺失)" -Color Red
        $allFilesOK = $false
    }
}

Write-ColorHost ""

# 4. 测试 Python.Runtime.dll 加载
Write-ColorHost "[4/4] 测试 .NET 程序集加载..." -Color Yellow

$pythonRuntimeDll = Join-Path $scriptDir "_internal\pythonnet\runtime\Python.Runtime.dll"
if (Test-Path $pythonRuntimeDll) {
    try {
        [System.Reflection.Assembly]::LoadFrom($pythonRuntimeDll) | Out-Null
        Write-ColorHost "   ✓ Python.Runtime.dll 加载成功" -Color Green
    } catch {
        Write-ColorHost "   ✗ Python.Runtime.dll 加载失败" -Color Red
        Write-ColorHost "   错误: $($_.Exception.Message)" -Color Red
        $allFilesOK = $false
    }
} else {
    Write-ColorHost "   ⚠ 跳过测试（文件不存在）" -Color Yellow
}

Write-ColorHost ""
Write-ColorHost "=======================================" -Color Cyan

# 汇总结果
if ($netVersionOK -and $allFilesOK) {
    Write-ColorHost "✓ 环境检查通过，可以正常运行 txrui" -Color Green
    Write-ColorHost ""
    Write-ColorHost "启动 txrui:" -Color Yellow
    Write-ColorHost "   .\txrui.exe" -Color Cyan
    $exitCode = 0
} else {
    Write-ColorHost "✗ 环境检查未通过，请解决上述问题" -Color Red
    $exitCode = 1
}

Write-ColorHost "=======================================" -Color Cyan
Write-ColorHost ""

if (-not $Silent) {
    Write-ColorHost "按任意键退出..." -Color Gray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}

exit $exitCode
