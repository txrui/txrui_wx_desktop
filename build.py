"""
构建和打包脚本 - 自动化 PyInstaller 构建、签名和分发包创建
"""
import subprocess
import sys
import shutil
from pathlib import Path
from datetime import datetime

# 配置
CERT_PATH = None  # 例如: "certs/txrui-cert.pfx" 或 None（不签名）
CERT_PASSWORD = None  # 证书密码或 None

# 颜色输出
class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_step(step_num, total, message):
    """打印构建步骤"""
    print(f"\n{Colors.CYAN}[{step_num}/{total}] {message}{Colors.END}")

def print_success(message):
    """打印成功信息"""
    print(f"{Colors.GREEN}✓ {message}{Colors.END}")

def print_warning(message):
    """打印警告信息"""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.END}")

def print_error(message):
    """打印错误信息"""
    print(f"{Colors.RED}✗ {message}{Colors.END}")

def run_command(cmd, shell=False):
    """运行命令并返回结果"""
    try:
        result = subprocess.run(cmd, shell=shell, check=True, 
                              capture_output=True, text=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

def main():
    """主构建流程"""
    root = Path(__file__).parent
    dist_dir = root / "dist" / "txrui"
    build_dir = root / "build"
    
    total_steps = 6 if CERT_PATH else 5
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*50}")
    print("    txrui 自动化构建脚本")
    print(f"{'='*50}{Colors.END}\n")
    
    # 步骤 1: 清理旧构建
    print_step(1, total_steps, "清理旧构建")
    for dir_path in [dist_dir, build_dir]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"   已删除: {dir_path.name}")
    print_success("清理完成")
    
    # 步骤 2: 运行 PyInstaller
    print_step(2, total_steps, "运行 PyInstaller")
    success, output = run_command([sys.executable, "-m", "PyInstaller", "txrui.spec"])
    if not success:
        print_error("PyInstaller 构建失败")
        print(output)
        return 1
    print_success("PyInstaller 构建完成")
    
    # 步骤 3: 复制启动器和脚本
    print_step(3, total_steps, "复制辅助文件")
    files_to_copy = [
        ("启动 txrui.bat", "启动器"),
        ("first_run_setup.ps1", "首次运行设置脚本"),
        ("verify_dotnet.ps1", "环境诊断脚本"),
        ("README_SETUP.md", "使用说明")
    ]
    
    for filename, description in files_to_copy:
        src = root / filename
        dst = dist_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            print(f"   ✓ {description}")
        else:
            print_warning(f"{filename} 不存在，跳过")
    
    print_success("辅助文件复制完成")
    
    # 步骤 4: 代码签名（可选）
    current_step = 4
    if CERT_PATH:
        print_step(current_step, total_steps, "对程序进行代码签名")
        cert_path = root / CERT_PATH if not Path(CERT_PATH).is_absolute() else Path(CERT_PATH)
        
        if not cert_path.exists():
            print_warning(f"证书文件不存在: {cert_path}")
            print_warning("跳过签名步骤")
        else:
            sign_script = root / "sign_exe.ps1"
            if sign_script.exists():
                cmd = [
                    "powershell", "-ExecutionPolicy", "Bypass",
                    "-File", str(sign_script),
                    "-CertPath", str(cert_path),
                    "-TargetDir", str(dist_dir)
                ]
                
                if CERT_PASSWORD:
                    cmd.extend(["-CertPassword", CERT_PASSWORD])
                
                success, output = run_command(cmd)
                if success:
                    print_success("代码签名完成")
                else:
                    print_error("代码签名失败")
                    print(output)
                    return 1
            else:
                print_warning("sign_exe.ps1 不存在，跳过签名")
        current_step += 1
    
    # 步骤 5: 验证构建
    print_step(current_step, total_steps, "验证构建")
    critical_files = [
        "txrui.exe",
        "_internal/pythonnet/runtime/Python.Runtime.dll",
        "启动 txrui.bat",
        "first_run_setup.ps1"
    ]
    
    all_ok = True
    for file_path in critical_files:
        full_path = dist_dir / file_path
        if full_path.exists():
            print(f"   ✓ {file_path}")
        else:
            print_error(f"{file_path} 缺失")
            all_ok = False
    
    if all_ok:
        print_success("构建验证通过")
    else:
        print_error("构建验证失败，有文件缺失")
        return 1
    
    current_step += 1
    
    # 步骤 6: 创建分发包
    print_step(current_step, total_steps, "创建分发包")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"txrui_{timestamp}.zip"
    zip_path = root / zip_name
    
    # 使用 PowerShell 的 Compress-Archive（更可靠）
    cmd = [
        "powershell", "-Command",
        f"Compress-Archive -Path '{dist_dir}\\*' -DestinationPath '{zip_path}' -Force"
    ]
    success, output = run_command(cmd)
    
    if success and zip_path.exists():
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print_success(f"分发包创建完成: {zip_name} ({size_mb:.1f} MB)")
    else:
        print_error("分发包创建失败")
        return 1
    
    # 完成
    print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*50}")
    print("    构建成功！")
    print(f"{'='*50}{Colors.END}\n")
    
    print(f"输出目录: {Colors.CYAN}{dist_dir}{Colors.END}")
    print(f"分发包: {Colors.CYAN}{zip_path}{Colors.END}")
    print(f"\n测试运行:")
    print(f"  {Colors.CYAN}cd {dist_dir}{Colors.END}")
    print(f"  {Colors.CYAN}.\\启动 txrui.bat{Colors.END}")
    print()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
