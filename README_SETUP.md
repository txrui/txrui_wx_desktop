# txrui 使用说明

## 快速开始

### 方式一：使用启动器（推荐）

双击运行 **`启动 txrui.bat`**

启动器会自动：
1. 检查并解除文件阻止
2. 验证 .NET Framework 环境
3. 测试关键组件
4. 启动 txrui 主程序

首次运行后会创建 `.setup_complete` 标记文件，之后启动会更快。

### 方式二：直接运行

如果启动器遇到问题，可以手动操作：

```powershell
# 1. 解除文件阻止（首次运行必须）
Get-ChildItem -Path . -Recurse | Unblock-File

# 2. 运行主程序
.\txrui.exe
```

## 常见问题

### 1. 启动时提示 ".NET 桥接加载失败"

**原因**：文件被 Windows 标记为"来自互联网"而阻止。

**解决方法**：
- 使用 `启动 txrui.bat`（会自动解除阻止）
- 或手动运行：`.\first_run_setup.ps1`

### 2. 提示缺少 .NET Framework

**解决方法**：
安装 .NET Framework 4.8：https://dotnet.microsoft.com/download/dotnet-framework/net48

### 3. Windows Defender SmartScreen 警告

**原因**：程序未使用商业代码签名证书。

**解决方法**：
- 点击"更多信息" → "仍要运行"
- 程序是安全的，警告只是因为缺少商业证书

### 4. 需要以管理员身份运行吗？

**不需要**。txrui 可以在普通用户权限下运行。

## 系统要求

- **操作系统**：Windows 10/11
- **.NET Framework**：4.6.2 或更高（建议安装 4.8）
- **微信**：Windows 桌面版

## 命令行参数

```bash
# 使用浏览器模式（而非桌面嵌入窗口）
txrui.exe --browser

# 指定端口
txrui.exe --port 18080

# 显示帮助
txrui.exe --help
```

## 诊断工具

如果遇到问题，可以运行诊断脚本：

```powershell
# 完整环境诊断（检查 .NET、DLL 阻止状态等）
.\verify_dotnet.ps1

# 首次运行设置（解除阻止 + 环境检查）
.\first_run_setup.ps1
```

## 文件说明

```
txrui/
├── txrui.exe                   # 主程序
├── 启动 txrui.bat               # 启动器（推荐使用）
├── first_run_setup.ps1         # 首次运行设置脚本
├── verify_dotnet.ps1           # 环境诊断脚本
├── config.toml                 # 配置文件
├── README_SETUP.md             # 本文件
├── _internal/                  # 程序依赖（Python、DLL 等）
│   ├── pythonnet/              # .NET 桥接组件
│   └── ...
└── webui/                      # Web 界面资源
```

## 卸载

直接删除整个 `txrui` 文件夹即可，程序不会在系统其他位置创建文件。

## 获取帮助

- **问题反馈**：[GitHub Issues](https://github.com/your-repo/txrui/issues)
- **文档**：[在线文档](https://your-docs-site.com)

## 开发者信息

- 使用 PyInstaller 打包
- Python 3.x + pythonnet + webview
- 开源协议：MIT（或你的实际协议）

---

**祝使用愉快！**
