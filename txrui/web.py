"""启动本地控制页面、桌面网页窗口和可选托盘。

关闭窗口时仅隐藏；托盘退出时停止运行时和服务。
缺少桌面网页依赖时输出浏览器访问地址，并等待键盘中断退出。
"""
from __future__ import annotations

import logging
import threading

from . import state as _st
from .paths import resource_dir

logger = logging.getLogger(__name__)


def run_web(runtime, bridge, host: str = "127.0.0.1", port: int = 17880,
            debug: bool = False) -> None:
    runtime.prepare_wechat()
    from .webserver import WebServer
    server = WebServer(bridge, host=host, port=port)
    url = server.start()
    _st.log(f"网页控制台: {url}")
    logger.info(f"[web] {url}")

    try:
        import webview  # type: ignore
    except ImportError:
        _st.log("未安装 pywebview，已降级为浏览器模式：请手动打开上面地址")
        print(f"[txrui] 请用浏览器打开: {url}")
        try:
            import threading as _th
            _th.Event().wait()  # 保持服务进程运行，等待键盘中断。
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
        return

    win = webview.create_window("txrui 控制面板", url, js_api=bridge,
                                width=1500, height=1000, min_size=(960, 620),
                                text_select=True)
    bridge._win = win

    # 托盘提供显示面板和退出入口；依赖不可用时仅记录日志。
    tray = None
    exiting = threading.Event()
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
    except Exception as e:
        _st.log(f"托盘未启用: {e}")

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
        except Exception as e:
            logger.warning("显示退出选择框失败，按完全退出处理: %s", e)
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
    finally:
        try:
            runtime.stop()
        except Exception:
            pass
        try:
            server.stop()
        except Exception:
            pass
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
