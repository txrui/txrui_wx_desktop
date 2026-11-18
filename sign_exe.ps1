# Windows 代码签名脚本
# 用于对 txrui.exe 和相关 DLL 文件进行数字签名

param(
    [Parameter(Mandatory=$true)]
    [string]$CertPath,          # 证书文件路径 (.pfx 或 .p12)
    
    [Parameter(Mandatory=$false)]
    [string]$CertPassword = "", # 证书密码（可选）
    
    [Parameter(Mandatory=$false)]
    [string]$Timestamp = "http://timestamp.digicert.com", # 时间戳服务器
    
    [Parameter(Mandatory=$false)]
    [string]$Description = "txrui - 微信桌面自动化工具",
    
    [Parameter(Mandatory=$false)]
    [string]$TargetDir = "dist\txrui"  # 目标目录
)

# 检查 signtool.exe 是否存在
$signtool = "signtool.exe"
$signtoolPaths = @(
    "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe",
    "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22000.0\x64\signtool.exe",
    "C:\Program Files (x86)\Windows Kits\10\bin\10.0.19041.0\x64\signtool.exe",
    "C:\Program Files (x86)\Windows Kits\10\App Certification Kit\signtool.exe"
)

$signtoolFound = $false
foreach ($path in $signtoolPaths) {
    if (Test-Path $path) {
        $signtool = $path
        $signtoolFound = $true
        Write-Host "✓ 找到 signtool: $path" -ForegroundColor Green
        break
    }
}

if (-not $signtoolFound) {
    # 尝试从系统路径找
    try {
        $result = Get-Command signtool.exe -ErrorAction Stop
        $signtool = $result.Source
        $signtoolFound = $true
        Write-Host "✓ 找到 signtool: $signtool" -ForegroundColor Green
    } catch {
        Write-Host "✗ 未找到 signtool.exe" -ForegroundColor Red
        Write-Host "请安装 Windows SDK: https://developer.microsoft.com/windows/downloads/windows-sdk/" -ForegroundColor Yellow
        exit 1
    }
}

# 检查证书文件
if (-not (Test-Path $CertPath)) {
    Write-Host "✗ 证书文件不存在: $CertPath" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "开始签名 txrui 程序文件" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "证书路径: $CertPath"
Write-Host "目标目录: $TargetDir"
Write-Host "时间戳服务器: $Timestamp"
Write-Host ""

# 构建签名命令
function Sign-File {
    param(
        [string]$FilePath
    )
    
    $fileName = Split-Path $FilePath -Leaf
    Write-Host "正在签名: $fileName ... " -NoNewline
    
    $args = @(
        "sign",
        "/f", $CertPath,
        "/d", $Description,
        "/t", $Timestamp,
        "/v"
    )
    
    # 如果提供了密码
    if ($CertPassword -ne "") {
        $args += "/p"
        $args += $CertPassword
    }
    
    $args += $FilePath
    
    try {
        $output = & $signtool $args 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓" -ForegroundColor Green
            return $true
        } else {
            Write-Host "✗" -ForegroundColor Red
            Write-Host "  错误: $output" -ForegroundColor Yellow
            return $false
        }
    } catch {
        Write-Host "✗" -ForegroundColor Red
        Write-Host "  异常: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

# 需要签名的文件列表
$filesToSign = @()

# 1. 主程序 exe
$exePath = Join-Path $TargetDir "txrui.exe"
if (Test-Path $exePath) {
    $filesToSign += $exePath
} else {
    Write-Host "⚠ 未找到主程序: $exePath" -ForegroundColor Yellow
}

# 2. _internal 目录下的关键 DLL（Python.Runtime.dll 等）
$criticalDlls = @(
    "_internal\pythonnet\runtime\Python.Runtime.dll",
    "_internal\clr_loader\ffi\dlls\ClrLoader.dll"
)

foreach ($dll in $criticalDlls) {
    $dllPath = Join-Path $TargetDir $dll
    if (Test-Path $dllPath) {
        $filesToSign += $dllPath
    }
}

# 3. 可选：签名所有 DLL（会花费较长时间）
# $allDlls = Get-ChildItem -Path (Join-Path $TargetDir "_internal") -Recurse -Filter "*.dll"
# $filesToSign += $allDlls.FullName

Write-Host "[1/3] 共找到 $($filesToSign.Count) 个文件需要签名" -ForegroundColor Yellow
Write-Host ""

# 执行签名
$successCount = 0
$failCount = 0

foreach ($file in $filesToSign) {
    if (Sign-File -FilePath $file) {
        $successCount++
    } else {
        $failCount++
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "签名完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "成功: $successCount" -ForegroundColor Green
Write-Host "失败: $failCount" -ForegroundColor Red

if ($failCount -gt 0) {
    exit 1
}

Write-Host ""
Write-Host "✓ 所有文件签名成功！" -ForegroundColor Green
Write-Host ""
Write-Host "验证签名（可选）:" -ForegroundColor Yellow
Write-Host "  signtool verify /pa $exePath" -ForegroundColor Cyan
