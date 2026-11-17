"""txrui 的 Windows 启动入口，提供桌面控制台和无界面运行模式。

默认启动本地网页服务及 pywebview 窗口；关闭窗口隐藏到托盘，托盘菜单负责退出。
缺少 pywebview 或 WebView2 时保持网页服务运行，供浏览器访问；--browser 强制使用浏览器模式。--debug 启用开发者工具。
--headless 直接启动窗口识别、消息采集和 WebSocket 连接，不提供控制台。
"""
from __future__ import annotations

import argparse
import logging

from txrui import state as _st
from txrui.runtime import Runtime
from txrui.webbridge import TxruiBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("txrui")


def main(debug: bool = False, browser: bool = False):
    from txrui import config as C
    if not C.CONNECTOR_TOKEN:
        _st.log("缺少 CONNECTOR_TOKEN：请在网页设置页填入 core 签发的令牌再点启动")
    rt = Runtime()
    bridge = TxruiBridge(rt)
    from txrui.web import run_web
    run_web(rt, bridge, host=C.WEB_HOST, port=C.WEB_PORT, debug=debug,
            browser=browser)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="txrui 控制面板（网页前端）")
    ap.add_argument("--debug", action="store_true", help="打开 WebView2 开发者工具")
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--browser", action="store_true", help="使用系统浏览器打开控制台，不启动内嵌桌面窗口")
    modes.add_argument("--headless", action="store_true", help="纯后台跑（无网页控制台）")
    args = ap.parse_args()
    if args.headless:
        import asyncio
        from txrui.backend import TxruiBackend
        from txrui.collector import poll_loop
        from txrui.runtime import resolve_ws_target
        from txrui.ws_client import TxruiClient
        from txrui import config as C

        async def _main():
            ws_url, ws_token, target = resolve_ws_target()
            if not ws_token:
                raise SystemExit(
                    f"缺少连接令牌：{'请在 config.toml 的 [astrbot] 段填 ASTRBOT_TOKEN' if target == 'astrbot' else '请在 config.toml 的 [core] 段填 CONNECTOR_TOKEN'}"
                )
            from txrui import state as _st2
            backend = TxruiBackend()
            backend.connect()
            _st2.set_field("backend_ok", True)
            _st2.set_field("running", True)
            _st2.set_field("core_ws_url", ws_url)
            _st2.set_field("backend_target", target)
            client = TxruiClient(ws_url, C.CONNECTOR_ID, ws_token,
                                 account_ids=C.WECHAT_ACCOUNT_ID,
                                 heartbeat_sec=C.HEARTBEAT_SEC)

            async def _send(account_id: str, chat_id: str, text: str) -> dict:
                from txrui import sender as _sender
                from txrui.filters import is_blocked
                blocked, reason = is_blocked(chat_id)
                if blocked:
                    _st2.note_blocked(chat_id, f"outbound:{reason}")
                    return {"ok": False, "unknown": False, "platform_message_id": "",
                            "error": f"blocked:{reason}"[:200]}
                try:
                    ok = _sender.send_text(backend._hwnd, chat_id, text or "")
                except Exception as e:  # noqa: BLE001
                    return {"ok": False, "unknown": True, "platform_message_id": "",
                            "error": f"send_exception:{e}"[:200]}
                if ok:
                    return {"ok": True, "unknown": False, "platform_message_id": "", "error": ""}
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": "visual_send_failed"}

            client.bind_sender(_send)
            poll_task = asyncio.create_task(poll_loop(backend, client, C.WECHAT_ACCOUNT_ID,
                                                      poll_sec=C.POLL_SEC))
            try:
                await client.run_forever()
            finally:
                poll_task.cancel()

        asyncio.run(_main())
    else:
        main(debug=args.debug, browser=args.browser)
