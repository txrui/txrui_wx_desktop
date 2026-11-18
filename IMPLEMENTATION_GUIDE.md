# txrui 中期改进方案 - 实施说明

## 改进内容

### 1. 自动化环境设置
- **`first_run_setup.ps1`** - 首次运行自动配置脚本
  - 自动解除所有文件的阻止状态（Unblock-File）
  - 检查 .NET Framework 版本
  - 验证关键 DLL 文件
  - 测试 Python.Runtime.dll 加载
  
### 2. 友好的启动器
- **`启动 txrui.bat`** - 一键启动脚本
  - 首次运行自动执行环境检查
  - 创建 `.setup_complete` 标记避免重复检查
  - 后续启动直接运行程序，速度更快

### 3. 完善的用户文档
- **`README_SETUP.md`** - 详细使用说明
  - 快速开始指南
  - 常见问题解答
  - 命令行参数说明
  - 诊断工具使用方法

### 4. 自动化构建脚本
- **`build.py`** - 一键构建、签名、打包
  - 自动清理旧构建
  - 运行 PyInstaller
  - 复制辅助脚本
  - 可选代码签名
  - 创建带时间戳的分发包

## 使用方法

### 对于开发者（构建发布包）

1. **标准构建（不签名）**：
```bash
python build.py
```

2. **带签名的构建**（需要先配置证书）：
```python
# 编辑 build.py，设置证书路径
CERT_PATH = "certs/txrui-cert.pfx"  # 或 "txrui-selfsigned.pfx"
CERT_PASSWORD = "your-password"

# 然后运行
python build.py
```

3. **手动构建**（传统方式）：
```bash
# 构建
pyinstaller txrui.spec

# 复制辅助文件到 dist/txrui/
copy "启动 txrui.bat" dist\txrui\
copy first_run_setup.ps1 dist\txrui\
copy verify_dotnet.ps1 dist\txrui\
copy README_SETUP.md dist\txrui\

# 打包
Compress-Archive -Path dist\txrui\* -DestinationPath txrui_release.zip
```

### 对于最终用户

1. **解压 zip 文件**到本地磁盘（如 `C:\txrui` 或 `D:\txrui`）

2. **双击运行 `启动 txrui.bat`**
   - 首次运行会自动：
     - ✓ 解除文件阻止
     - ✓ 检查 .NET Framework
     - ✓ 验证环境
   - 后续启动直接运行程序

3. **（可选）如果遇到问题**：
```powershell
# 运行环境诊断
.\verify_dotnet.ps1

# 手动运行首次设置
.\first_run_setup.ps1
```

## 改进效果

### 用户体验改进
- ✅ **零手动配置**：不需要用户手动运行 `Unblock-File`
- ✅ **自动诊断**：首次运行自动检查环境，发现问题会给出明确提示
- ✅ **更快启动**：首次设置后，后续启动无需重复检查
- ✅ **清晰文档**：README 包含所有常见问题的解决方案

### 与之前方案对比

| 方案 | 用户操作 | 技术难度 | 成本 |
|------|---------|---------|------|
| **旧方案** | 手动运行 `Unblock-File` | 需要 PowerShell 知识 | 免费 |
| **中期方案（当前）** | 双击启动器 | 无需技术知识 | 免费 |
| **长期方案** | 双击 exe | 无需技术知识 | $100-500/年 |

## 文件变更清单

### 新增文件
```
txrui_desktop/
├── first_run_setup.ps1          # 首次运行设置脚本
├── 启动 txrui.bat                # 启动器
├── README_SETUP.md              # 用户使用说明
├── build.py                     # 自动化构建脚本
└── IMPLEMENTATION_GUIDE.md      # 本文件
```

### 修改文件
```
txrui.spec  # 添加了辅助脚本到 datas
```

### 保留文件（已创建，按需使用）
```
verify_dotnet.ps1               # 环境诊断（包含在分发包中）
sign_exe.ps1                    # 代码签名脚本（开发者使用）
create_selfsigned_cert.ps1      # 生成自签名证书（开发者使用）
CODE_SIGNING_GUIDE.md           # 代码签名完整指南（开发者参考）
```

## 测试清单

### 开发环境测试
- [ ] 运行 `python build.py` 成功构建
- [ ] 检查 `dist/txrui/` 包含所有必要文件
- [ ] 验证生成的 zip 包可正常解压

### 全新环境测试
- [ ] 在从未运行过 txrui 的 Windows 机器上测试
- [ ] 从 zip 解压到本地磁盘
- [ ] 双击 `启动 txrui.bat`
- [ ] 验证首次设置脚本正确执行
- [ ] 验证 txrui 正常启动（无 .NET 加载错误）
- [ ] 关闭后再次启动，验证快速启动（跳过首次设置）

### 问题场景测试
- [ ] 在未安装 .NET Framework 4.6.2+ 的系统测试（应给出明确提示）
- [ ] 删除 `.setup_complete` 文件，重新运行，验证重新执行首次设置
- [ ] 测试 `verify_dotnet.ps1` 诊断脚本输出

## 下一步（可选）

### 进一步改进建议
1. **在线安装器**：创建轻量级安装器，从网络下载文件（避免 Zone.Identifier）
2. **自动更新**：实现自动检查和更新功能
3. **安装到 Program Files**：提供正式的 MSI 安装包
4. **商业证书**：购买 EV 证书消除所有安全警告

### 代码签名（如果预算允许）
参考 `CODE_SIGNING_GUIDE.md` 实施：
1. 购买代码签名证书（DigiCert/Sectigo）
2. 配置 `build.py` 中的证书路径
3. 每次发布自动签名

## 问题反馈

如果此方案在实际使用中遇到问题，请：
1. 运行 `verify_dotnet.ps1` 收集诊断信息
2. 检查 `.setup_complete` 是否正确创建
3. 查看启动器是否正确调用 PowerShell 脚本

---

**实施完成！** 现在你的用户只需双击 `启动 txrui.bat` 即可自动完成所有环境设置。
