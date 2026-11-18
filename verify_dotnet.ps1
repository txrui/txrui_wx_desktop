# .NET Framework 诊断脚本
# 用于排查 pythonnet 加载失败问题

Write-Host "========================================" -ForegroundColor Cyan
Write-Host ".NET Framework 环境诊断" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 .NET Framework 版本
Write-Host "[1] 检查已安装的 .NET Framework 版本" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$netVersions = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\' -ErrorAction SilentlyContinue
if ($netVersions) {
    $release = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\').Release
    $version = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\').Version
    
    Write-Host "Release 编号: $release" -ForegroundColor Green
    Write-Host "版本号: $version" -ForegroundColor Green
    
    # 根据 Release 编号判断版本
    if ($release -ge 528040) { Write-Host "✓ .NET Framework 4.8 或更高" -ForegroundColor Green }
    elseif ($release -ge 461808) { Write-Host "✓ .NET Framework 4.7.2 或更高" -ForegroundColor Green }
    elseif ($release -ge 394802) { Write-Host "✓ .NET Framework 4.6.2 或更高" -ForegroundColor Green }
    else { Write-Host "✗ 版本过低，需要 4.6.2 或更高" -ForegroundColor Red }
} else {
    Write-Host "✗ 未找到 .NET Framework 4.x" -ForegroundColor Red
}
Write-Host ""

# 2. 检查 DLL 文件是否存在
Write-Host "[2] 检查关键 DLL 文件" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$dllPath = "C:\txrui\_internal\pythonnet\runtime\Python.Runtime.dll"
if (Test-Path $dllPath) {
    Write-Host "✓ 找到 Python.Runtime.dll" -ForegroundColor Green
    $dll = Get-Item $dllPath
    Write-Host "  文件大小: $($dll.Length) 字节"
    Write-Host "  修改时间: $($dll.LastWriteTime)"
    
    # 检查文件是否被阻止
    $zone = Get-Item $dllPath -Stream Zone.Identifier -ErrorAction SilentlyContinue
    if ($zone) {
        Write-Host "  ⚠ 文件被标记为来自互联网（已阻止）" -ForegroundColor Red
        Write-Host "  执行以下命令解除阻止:" -ForegroundColor Yellow
        Write-Host "  Unblock-File -Path '$dllPath'" -ForegroundColor Cyan
    } else {
        Write-Host "  ✓ 文件未被阻止" -ForegroundColor Green
    }
} else {
    Write-Host "✗ 未找到 Python.Runtime.dll" -ForegroundColor Red
    Write-Host "  预期路径: $dllPath"
}
Write-Host ""

# 3. 检查整个 pythonnet 目录的阻止状态
Write-Host "[3] 检查 pythonnet 目录中所有 DLL 的阻止状态" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$pythonnetDir = "C:\txrui\_internal\pythonnet"
if (Test-Path $pythonnetDir) {
    $blockedDlls = Get-ChildItem -Path $pythonnetDir -Recurse -Filter "*.dll" | 
        Where-Object { Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue }
    
    if ($blockedDlls) {
        Write-Host "⚠ 发现 $($blockedDlls.Count) 个被阻止的 DLL 文件:" -ForegroundColor Red
        $blockedDlls | ForEach-Object { Write-Host "  - $($_.FullName)" -ForegroundColor Yellow }
        Write-Host ""
        Write-Host "执行以下命令批量解除阻止:" -ForegroundColor Yellow
        Write-Host "Get-ChildItem -Path '$pythonnetDir' -Recurse -Filter '*.dll' | Unblock-File" -ForegroundColor Cyan
    } else {
        Write-Host "✓ 未发现被阻止的 DLL 文件" -ForegroundColor Green
    }
} else {
    Write-Host "✗ 未找到 pythonnet 目录: $pythonnetDir" -ForegroundColor Red
}
Write-Host ""

# 4. 检查 _internal 目录的其他 DLL
Write-Host "[4] 检查 _internal 目录中所有被阻止的文件" -ForegroundColor Yellow
Write-Host "----------------------------------------"

$internalDir = "C:\txrui\_internal"
if (Test-Path $internalDir) {
    $allBlockedFiles = Get-ChildItem -Path $internalDir -Recurse -Include "*.dll","*.pyd" | 
        Where-Object { Get-Item $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue }
    
    if ($allBlockedFiles) {
        Write-Host "⚠ 发现 $($allBlockedFiles.Count) 个被阻止的文件" -ForegroundColor Red
        Write-Host ""
        Write-Host "执行以下命令批量解除阻止所有文件:" -ForegroundColor Yellow
        Write-Host "Get-ChildItem -Path '$internalDir' -Recurse | Unblock-File" -ForegroundColor Cyan
    } else {
        Write-Host "✓ 未发现被阻止的文件" -ForegroundColor Green
    }
}
Write-Host ""

# 5. 测试加载 .NET 程序集
Write-Host "[5] 测试加载 Python.Runtime.dll" -ForegroundColor Yellow
Write-Host "----------------------------------------"

if (Test-Path $dllPath) {
    try {
        [System.Reflection.Assembly]::LoadFrom($dllPath) | Out-Null
        Write-Host "✓ 成功加载程序集" -ForegroundColor Green
    } catch {
        Write-Host "✗ 加载失败" -ForegroundColor Red
        Write-Host "  错误信息: $($_.Exception.Message)" -ForegroundColor Red
        
        if ($_.Exception.Message -like "*FileLoadException*" -or $_.Exception.Message -like "*blocked*") {
            Write-Host "  ⚠ 可能是文件被阻止导致的" -ForegroundColor Yellow
        }
    }
}
Write-Host ""

# 6. 检查应用程序是否从压缩包直接运行
Write-Host "[6] 检查文件路径" -ForegroundColor Yellow
Write-Host "----------------------------------------"

if ($internalDir -match "Temp|AppData\\Local\\Temp|\.zip|\.rar") {
    Write-Host "⚠ 警告: 程序可能在临时目录或压缩包中运行" -ForegroundColor Red
    Write-Host "  请将程序完整解压到本地磁盘（如 C:\txrui 或 D:\txrui）后再运行" -ForegroundColor Yellow
} else {
    Write-Host "✓ 程序路径正常: $internalDir" -ForegroundColor Green
}
Write-Host ""

# 7. 总结和建议
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "诊断总结和建议操作" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "如果发现问题，请依次尝试以下操作:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1. 解除所有 DLL 文件的阻止状态:" -ForegroundColor White
Write-Host "   Get-ChildItem -Path 'C:\txrui\_internal' -Recurse | Unblock-File" -ForegroundColor Cyan
Write-Host ""
Write-Host "2. 确认已安装 .NET Framework 4.8:" -ForegroundColor White
Write-Host "   https://dotnet.microsoft.com/download/dotnet-framework/net48" -ForegroundColor Cyan
Write-Host ""
Write-Host "3. 以管理员身份运行 txrui 程序" -ForegroundColor White
Write-Host ""
Write-Host "4. 临时使用浏览器模式:" -ForegroundColor White
Write-Host "   txrui --browser" -ForegroundColor Cyan
Write-Host ""
