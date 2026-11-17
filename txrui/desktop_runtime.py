"""Windows 内嵌控制台的 .NET Framework 加载与无窗口自检。"""
from __future__ import annotations

import sys

from .paths import resource_dir


def prepare_desktop_runtime() -> None:
    """在 pywebview 导入 clr 前指定应用域配置，不依赖机器上的 .NET Core。"""
    if sys.platform != "win32":
        return
    config = resource_dir() / "txrui.netfx.config"
    if not config.is_file():
        raise RuntimeError(f"缺少 .NET 加载配置：{config}")
    try:
        import pythonnet
        if pythonnet.get_runtime_info() is None:
            pythonnet.load("netfx", config_file=str(config))
    except Exception as exc:
        raise RuntimeError(
            "无法加载 Windows 桌面 .NET 桥接。请确认系统提供 .NET Framework 4.6.2 或更高版本，"
            "确认已完整解压程序到本地磁盘且 DLL 未被安全策略拦截；"
            "可用 --browser 临时运行。原始错误：" + str(exc)
        ) from exc


def initialize_webview():
    """加载受支持的 WinForms/WebView2 后端；缺少 WebView2 时由调用方回退。"""
    prepare_desktop_runtime()
    from webview.guilib import initialize
    return initialize("edgechromium")


def check_desktop_runtime() -> dict[str, str]:
    """实际加载 WinForms 和 WebView2 桥接；不创建窗口、不操作微信。"""
    gui = initialize_webview()
    renderer = getattr(gui, "renderer", "unknown")
    if renderer != "edgechromium":
        raise RuntimeError(
            "未检测到 Microsoft Edge WebView2 Runtime，请安装 x64 Evergreen Runtime；"
            "旧版 IE/MSHTML 无法可靠运行控制台。"
        )
    import pythonnet
    return {"renderer": renderer, "runtime": str(pythonnet.get_runtime_info())}
