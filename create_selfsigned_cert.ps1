# 快速生成自签名证书并签名（仅用于测试）
# 适用于开发和测试环境，不建议用于生产发布

param(
    [Parameter(Mandatory=$false)]
    [string]$Subject = "CN=txrui Developer, O=txrui, C=CN",
    
    [Parameter(Mandatory=$false)]
    [string]$Password = "txrui2024",
    
    [Parameter(Mandatory=$false)]
    [string]$OutputCert = "txrui-selfsigned.pfx"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "生成自签名代码签名证书" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "⚠ 警告：自签名证书仅用于测试，用户仍会看到安全警告" -ForegroundColor Yellow
Write-Host ""

# 检查是否以管理员身份运行
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "⚠ 建议以管理员身份运行此脚本" -ForegroundColor Yellow
}

Write-Host "1. 创建自签名证书..." -ForegroundColor Yellow

try {
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $Subject `
        -KeyExportPolicy Exportable `
        -KeySpec Signature `
        -KeyLength 2048 `
        -KeyAlgorithm RSA `
        -HashAlgorithm SHA256 `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -NotAfter (Get-Date).AddYears(5)
    
    Write-Host "   ✓ 证书已创建" -ForegroundColor Green
    Write-Host "   主题: $($cert.Subject)"
    Write-Host "   指纹: $($cert.Thumbprint)"
    Write-Host "   有效期至: $($cert.NotAfter)"
} catch {
    Write-Host "   ✗ 创建证书失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "2. 导出证书为 .pfx 文件..." -ForegroundColor Yellow

try {
    $securePassword = ConvertTo-SecureString -String $Password -Force -AsPlainText
    Export-PfxCertificate -Cert $cert -FilePath $OutputCert -Password $securePassword | Out-Null
    
    Write-Host "   ✓ 证书已导出: $OutputCert" -ForegroundColor Green
    Write-Host "   密码: $Password"
} catch {
    Write-Host "   ✗ 导出证书失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "3. 对 txrui.exe 进行签名..." -ForegroundColor Yellow

$exePath = "dist\txrui\txrui.exe"
if (-not (Test-Path $exePath)) {
    Write-Host "   ⚠ 未找到 $exePath，跳过签名" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "证书已生成，可以稍后使用以下命令签名:" -ForegroundColor Cyan
    Write-Host "   .\sign_exe.ps1 -CertPath '$OutputCert' -CertPassword '$Password'"
} else {
    Write-Host "   正在签名..."
    
    if (Test-Path ".\sign_exe.ps1") {
        $result = & ".\sign_exe.ps1" -CertPath $OutputCert -CertPassword $Password
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   ✓ 签名成功" -ForegroundColor Green
        } else {
            Write-Host "   ✗ 签名失败" -ForegroundColor Red
        }
    } else {
        Write-Host "   ⚠ 未找到 sign_exe.ps1 脚本" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "证书文件: $OutputCert" -ForegroundColor Green
Write-Host "证书密码: $Password" -ForegroundColor Green
Write-Host ""
Write-Host "下一步:" -ForegroundColor Yellow
Write-Host "1. 构建程序: pyinstaller txrui.spec"
Write-Host "2. 签名程序: .\sign_exe.ps1 -CertPath '$OutputCert' -CertPassword '$Password'"
Write-Host ""
Write-Host "⚠ 重要提示:" -ForegroundColor Yellow
Write-Host "- 自签名证书不会被 Windows SmartScreen 自动信任"
Write-Host "- 用户下载后仍需手动解除阻止或接受安全警告"
Write-Host "- 对于生产发布，建议购买商业代码签名证书（参考 CODE_SIGNING_GUIDE.md）"
Write-Host ""
