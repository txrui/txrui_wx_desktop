"""启动本地控制页面、桌面网页窗口和可选托盘。

关闭窗口时仅隐藏；托盘退出时停止运行时和服务。
缺少桌面网页依赖或 WebView2 不可用时，自动改用系统浏览器访问控制台。
"""
from __future__ import annotations

import logging
import sys
import threading

from . import state as _st
from .paths import resource_dir

logger = logging.getLogger(__name__)


def _serve_in_browser(url: str) -> None:
    """尝试打开系统浏览器，并保持本地 HTTP 服务直到用户中断。"""
    _st.log(f"桌面网页窗口不可用，已切换浏览器模式: {url}")
    print(f"[txrui] 请用浏览器打开: {url}")
    try:
        import webbrowser
        if not webbrowser.open(url):
            logger.info("未能自动打开系统浏览器，请手动访问 %s", url)
    except Exception as exc:  # noqa: BLE001
        logger.info("自动打开系统浏览器失败，请手动访问 %s: %s", url, exc)
    try:
        threading.Event().wait()  # 保持服务进程运行，等待键盘中断。
    except KeyboardInterrupt:
        pass


def run_web(runtime, bridge, host: str = "127.0.0.1", port: int = 17880,
            debug: bool = False, browser: bool = False) -> None:
    runtime.prepare_wechat()
    from .webserver import WebServer
    server = WebServer(bridge, host=host, port=port)
    url = server.start()
    _st.log(f"网页控制台: {url}")
    logger.info("[web] %s", url)

    tray = None
    exiting = threading.Event()
    win = None
    try:
        if browser:
            _serve_in_browser(url)
            return

        try:
            from .desktop_runtime import initialize_webview, prepare_desktop_runtime
            prepare_desktop_runtime()
            import webview  # type: ignore
            if sys.platform == "win32":
                backend = initialize_webview()
                if getattr(backend, "renderer", None) != "edgechromium":
                    raise RuntimeError(
                        "未检测到 Microsoft Edge WebView2 Runtime，"
                        "请安装 x64 Evergreen Runtime 或使用 --browser。"
                    )
        except Exception as exc:  # noqa: BLE001
            # 某些环境在导入阶段就会因 WebView2/.NET 运行时缺失而失败。
            logger.exception("导入桌面网页依赖失败，改用浏览器模式")
            _st.log(f"桌面网页依赖不可用，已降级为浏览器模式: {exc}")
            _serve_in_browser(url)
            return

        try:
            win = webview.create_window("txrui 控制面板", url, js_api=bridge,
                                       width=1500, height=1000, min_size=(960, 620),
                                       text_select=True)
            bridge._win = win
        except Exception as exc:  # noqa: BLE001
            # pywebview 可能已安装，但 Server 2019 未安装 WebView2，
            # 或当前会话没有可用的桌面 WebView 后端。
            logger.exception("创建桌面网页窗口失败，改用浏览器模式")
            _st.log(f"桌面窗口创建失败，已降级为浏览器模式: {exc}")
            _serve_in_browser(url)
            return

        # 托盘提供显示面板和退出入口；依赖不可用时仅记录日志。
        try:
            import pystray
            from PIL import Image, ImageDraw

            def _icon():
                logo = resource_dir() / "logo.png"
                if logo.is_file():
                    with Image.open(logo) as source:
                        return source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
                im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                d = ImageDraw.Draw(im)
                d.ellipse((4, 4, 60, 60), fill=(45, 120, 220, 255))
                d.text((22, 18), "Tx", fill=(255, 255, 255, 255))
                return im

            def _show(icon=None, item=None):
                try:
                    win.show()
                except Exception:
                    pass

            def _shutdown(icon=None, item=None):
                exiting.set()
                try:
                    runtime.stop()
                except Exception:
                    logger.exception("停止运行时失败")
                try:
                    server.stop()
                except Exception:
                    logger.exception("停止本地服务失败")
                if tray is not None:
                    try:
                        tray.stop()
                    except Exception:
                        pass

            def _quit(icon=None, item=None):
                _shutdown(icon, item)
                try:
                    win.destroy()
                except Exception:
                    pass

            tray = pystray.Icon("txrui", _icon(), "txrui 控制面板",
                                pystray.Menu(pystray.MenuItem("打开面板", _show, default=True),
                                             pystray.Menu.SEPARATOR,
                                             pystray.MenuItem("退出", _quit)))
            threading.Thread(target=tray.run, daemon=True, name="txrui-tray").start()
        except Exception as exc:  # noqa: BLE001
            _st.log(f"托盘未启用: {exc}")

        def _on_closing():
            if exiting.is_set():
                return True
            # “是”完全退出，“否”隐藏到托盘继续运行。
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                exit_app = messagebox.askyesno(
                    "退出 txrui", "选择“是”完全退出程序；选择“否”最小化到后台运行。",
                    parent=root)
                root.destroy()
            except Exception as exc:  # noqa: BLE001
                logger.warning("显示退出选择框失败，按完全退出处理: %s", exc)
                exit_app = True
            if not exit_app:
                try:
                    win.hide()
                except Exception:
                    pass
                return False
            _shutdown()
            return True

        win.events.closing += _on_closing
        try:
            icon_path = resource_dir() / "logo.ico"
            webview.start(debug=bool(debug),
                          icon=str(icon_path) if icon_path.is_file() else None)
        except Exception as exc:  # noqa: BLE001
            # import 成功不代表 WebView2 运行时、pythonnet 或当前桌面会话可用。
            logger.exception("启动桌面网页窗口失败，改用浏览器模式")
            _st.log(f"桌面窗口启动失败，已降级为浏览器模式: {exc}")
            try:
                if win is not None:
                    win.destroy()
            except Exception:
                pass
            _serve_in_browser(url)
    finally:
        try:
            runtime.stop()
        except Exception:
            logger.exception("停止运行时失败")
        try:
            server.stop()
        except Exception:
            logger.exception("停止本地服务失败")
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
