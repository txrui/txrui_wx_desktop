"""在后台事件循环中组合视觉后端、采集轮询和网络客户端。

发送钩子负责切换并复验目标会话类型；界面通过共享状态读取运行结果。
媒体优先经 WebSocket 获取，非 AstrBot 模式可尝试 HTTP 下载。
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading

from . import state as _st

logger = logging.getLogger(__name__)

#: 媒体段类型 → 默认扩展名（发送时拼文件名用）
_MEDIA_EXT = {
    "image": ".png", "file": ".bin", "video": ".mp4",
    "sticker": ".png", "emoji": ".png", "audio": ".amr",
}


def _sender_ext_for(seg_type: str) -> str:
    """媒体段类型 → 默认扩展名。"""
    return _MEDIA_EXT.get(str(seg_type or "").lower(), ".bin")


def _suffix_for(filename: str) -> str:
    """按文件名给扩展名（保底 .bin）。"""
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext and len(ext) <= 8 and ext[1:].isalnum():
        return ext
    return ".bin"


def resolve_ws_target() -> tuple[str, str, str]:
    """决定连哪个 WS 服务端。

    返回 `(ws_url, token, target)`：
    - `ASTRBOT_ENABLED=1` → 连 AstrBot 插件的 WS 服务端，target="astrbot"
    - 否则 → 连 core，target="core"

    AstrBot 直连时 token 优先取 `ASTRBOT_TOKEN`，为空则回退 `CONNECTOR_TOKEN`
    （两者应当一致，配置时只需填一个）。
    """
    from . import config as C

    enabled = str(C.ASTRBOT_ENABLED or "0").strip().lower()
    if enabled in ("1", "true", "yes", "on"):
        ws_url = str(C.ASTRBOT_WS_URL or "ws://127.0.0.1:8788").strip()
        token = str(C.ASTRBOT_TOKEN or "").strip() or str(C.CONNECTOR_TOKEN or "").strip()
        return ws_url, token, "astrbot"
    return str(C.CORE_WS_URL or "").strip(), str(C.CONNECTOR_TOKEN or "").strip(), "core"


async def _fetch_blob(media_id: str, url: str, filename: str,
                      client=None) -> tuple[bytes, str]:
    """优先通过 WebSocket 获取媒体；非 AstrBot 模式可尝试 HTTP 地址。

    HTTP 请求不附加认证信息；依次尝试媒体标识路径和提供的地址。
    获取失败返回空字节及原文件名。
    """
    if not media_id and not url:
        return b"", filename
    # 主路：WS 取回
    if client is not None and media_id:
        try:
            res = await client.fetch_media(media_id)
            if res.get("ok") and res.get("data"):
                return res["data"], (res.get("filename") or filename)
            logger.debug(f"WS 取媒体 blob 失败: {res.get('error', '')}")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"WS 取媒体 blob 异常: {e}")
    # AstrBot 直连模式不尝试 HTTP 下载，直接返回空数据。
    from . import config as _C

    if str(_C.ASTRBOT_ENABLED or "0").strip().lower() in ("1", "true", "yes", "on"):
        logger.debug("AstrBot 直连模式：跳过 REST blob 兜底")
        return b"", filename
    # 兜底：REST
    try:
        import httpx
        from . import config as C
        base = str(C.CORE_WS_URL or "")
        http_base = base.replace("ws://", "http://").replace("wss://", "https://")
        # 去掉 ws 路径尾巴，只留 scheme://host:port
        if "://" in http_base:
            http_base = http_base.split("://", 1)[0] + "://" + http_base.split("://", 1)[1].split("/", 1)[0]
        urls = []
        if media_id:
            urls.append(f"{http_base}/api/v1/media/blobs/{media_id}")
        if url:
            if url.startswith("http://") or url.startswith("https://"):
                urls.append(url)
            else:
                urls.append(f"{http_base}/{url.lstrip('/')}")
        async with httpx.AsyncClient(timeout=30.0) as cli:
            for u in urls:
                try:
                    resp = await cli.get(u)
                    if resp.status_code == 200 and resp.content:
                        name = filename
                        cd = resp.headers.get("content-disposition", "")
                        if cd:
                            import re as _re
                            m = _re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
                            if m:
                                name = m.group(1).strip() or name
                        return resp.content, name
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"REST 取媒体 blob 失败 {u}: {e}")
        return b"", filename
    except Exception as e:  # noqa: BLE001
        logger.warning(f"取媒体 blob 异常: {e}")
        return b"", filename


class Runtime:
    #: 当前运行中的 Runtime 单例（供 recall 等需要访问 backend 的模块用）
    _current: "Runtime | None" = None

    def __init__(self):
        self.backend = None
        self.client = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._main_task: asyncio.Task | None = None

    @classmethod
    def current_backend(cls):
        """当前活跃的 backend（没有则 None）。"""
        rt = cls._current
        return rt.backend if rt is not None else None

    def prepare_wechat(self) -> bool:
        """只连接视觉后端并应用窗口/DPI，不开启采集或网络连接。"""
        from .backend import TxruiBackend
        from . import capture as _cap
        from . import scale as _scale

        try:
            backend = TxruiBackend()
            backend.connect()
        except Exception as e:
            _st.set_field("backend_ok", False)
            _st.log(f"启动时微信窗口检查未完成: {e}；可在微信登录后点击启动采集重试")
            return False
        self.backend = backend
        _st.set_field("backend_ok", True)
        _st.set_field("hwnd", f"0x{backend._hwnd:x}")
        rect = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(backend._hwnd))
        _st.set_field("wechat_window_rect", list(rect) if rect else None)
        measured = _cap.monitor_dpi_scale(backend._hwnd)
        _st.set_field("wechat_measured_scale", measured)
        _st.set_field("wechat_active_scale", _scale.active_scale())
        _st.log(f"启动检查完成：微信位置/尺寸={rect}，实测缩放={measured}%，"
                f"生效档位={_scale.active_scale()}%，截图识别区域已自动应用")
        return True

    def start(self) -> None:
        from . import config as C
        from .backend import TxruiBackend
        from .collector import poll_loop
        from .ws_client import TxruiClient

        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("上一轮采集尚未停止，请稍后重试")
        # 仅确认旧线程退出后，才允许开始新一轮。
        self.stop_event.clear()

        Runtime._current = self
        _st.set_field("running", True)
        ws_url, ws_token, target = resolve_ws_target()
        _st.set_field("core_ws_url", ws_url)
        _st.set_field("backend_target", target)
        _st.set_field("connector_id", C.CONNECTOR_ID)
        _st.set_field("account_id", C.WECHAT_ACCOUNT_ID)
        _st.log(f"连接目标: {target} ({ws_url})")

        backend = TxruiBackend()
        backend.connect()
        _st.set_field("backend_ok", True)
        _st.set_field("hwnd", f"0x{backend._hwnd:x}" if backend._hwnd else "")
        _st.log(f"后端已连接 hwnd={_st.snapshot().get('hwnd')}")
        self.backend = backend

        client = TxruiClient(ws_url, C.CONNECTOR_ID, ws_token,
                             account_ids=C.WECHAT_ACCOUNT_ID,
                             heartbeat_sec=C.HEARTBEAT_SEC)

        async def _send(account_id: str, chat_id: str, text: str,
                        chat_type: str = "") -> dict:
            """过滤发送目标，切换会话并复验类型后执行文本粘贴发送。

            有效的下行类型优先，否则按会话名推断；类型不符时拒绝发送。
            """
            from .filters import is_blocked
            blocked, reason = is_blocked(chat_id)
            if blocked:
                _st.note_blocked(chat_id, f"outbound:{reason}")
                _st.log(f"[拦截发送] {chat_id!r} ({reason}) 拒绝下发")
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": f"blocked:{reason}"[:200]}
            # 目标会话类型（core 带的优先，否则按会话名判定）
            expect_type = str(chat_type or "").strip().lower()
            if expect_type not in ("private", "group"):
                expect_type = ""
            if not expect_type:
                det = backend.resolve_chat_type(chat_id)
                expect_type = det.get("chat_type") or "private"
            # 切到目标会话再发：标题复验不过则拒绝，避免消息发错会话
            try:
                if not backend.ensure_chat(chat_id):
                    _st.bump("sent_fail")
                    _st.log(f"[发送拒绝] 切不到会话 {chat_id!r}（列表找不到/标题复验不过）")
                    return {"ok": False, "unknown": False, "platform_message_id": "",
                            "error": f"switch_chat_failed:{chat_id}"[:200]}
            except Exception as e:
                _st.bump("sent_fail")
                return {"ok": False, "unknown": True, "platform_message_id": "",
                        "error": f"switch_exception:{e}"[:200]}
            # 会话类型复验：切换后读标题得到的实际类型必须与期望一致
            try:
                actual = backend.current_chat_type()
                if actual and expect_type and actual != expect_type:
                    _st.bump("sent_fail")
                    _st.log(f"[发送拒绝] 会话类型不符：目标={chat_id!r} "
                            f"期望={expect_type} 实际={actual}")
                    return {"ok": False, "unknown": False, "platform_message_id": "",
                            "error": f"chat_type_mismatch:{expect_type}!={actual}"[:200]}
            except Exception:
                pass
            from . import sender as _sender
            try:
                ok = _sender.send_text(backend._hwnd, chat_id, text or "")
            except Exception as e:
                _st.bump("sent_fail")
                return {"ok": False, "unknown": True, "platform_message_id": "",
                        "error": f"send_exception:{e}"[:200]}
            _st.bump("sent_ok" if ok else "sent_fail")
            if ok:
                _st.log(f"[发送] {chat_id!r} type={expect_type} 已粘贴发送")
                return {"ok": True, "unknown": False, "platform_message_id": "", "error": ""}
            return {"ok": False, "unknown": False, "platform_message_id": "",
                    "error": "visual_send_failed"}

        client.bind_sender(_send)

        async def _send_media(account_id: str, chat_id: str, seg_type: str,
                              segment: dict, chat_type: str = "") -> dict:
            """获取媒体字节，切换并复验目标会话类型后按临时文件发送。

            媒体标识和地址均不可用，或未取到数据时返回失败。
            """
            from . import media_grab as _mg
            from . import sender as _sender

            # 使用媒体标识或地址从服务端获取数据，不查找本地缓存。
            data = b""
            filename = str(segment.get("text") or "") or f"media{_sender_ext_for(seg_type)}"
            media_id = str(segment.get("media_id") or "")
            url = str(segment.get("url") or "")
            if media_id or url:
                data, filename = await _fetch_blob(media_id, url, filename, client=client)
            if not data:
                # core 上没有本体（占位段）：如实回失败
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": "no_media_blob:核心无媒体本体（占位段无法直发）"}
            # 2) 切到目标会话再发
            try:
                if not backend.ensure_chat(chat_id):
                    _st.bump("sent_fail")
                    return {"ok": False, "unknown": False, "platform_message_id": "",
                            "error": f"switch_chat_failed:{chat_id}"[:200]}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "unknown": True, "platform_message_id": "",
                        "error": f"switch_exception:{str(e)[:160]}"}
            # 2.5) 会话类型复验（与文本发送同口径）
            expect_type = str(chat_type or "").strip().lower()
            if expect_type not in ("private", "group"):
                expect_type = backend.resolve_chat_type(chat_id).get("chat_type") or "private"
            try:
                actual = backend.current_chat_type()
                if actual and actual != expect_type:
                    _st.bump("sent_fail")
                    _st.log(f"[发送拒绝] 会话类型不符：目标={chat_id!r} "
                            f"期望={expect_type} 实际={actual}")
                    return {"ok": False, "unknown": False, "platform_message_id": "",
                            "error": f"chat_type_mismatch:{expect_type}!={actual}"[:200]}
            except Exception:
                pass
            # 3) 粘贴发出
            try:
                if seg_type in ("image", "sticker"):
                    ok = _sender.send_image_bytes(backend._hwnd, data,
                                                  suffix=_suffix_for(filename))
                else:
                    ok = _sender.send_media_bytes(backend._hwnd, chat_id, data,
                                                  suffix=_suffix_for(filename),
                                                  filename=filename)
            except Exception as e:  # noqa: BLE001
                _st.bump("sent_fail")
                return {"ok": False, "unknown": True, "platform_message_id": "",
                        "error": f"send_exception:{str(e)[:160]}"}
            _st.bump("sent_ok" if ok else "sent_fail")
            if ok:
                return {"ok": True, "unknown": False, "platform_message_id": "",
                        "error": ""}
            return {"ok": False, "unknown": False, "platform_message_id": "",
                    "error": "media_send_failed"}

        client.bind_media_sender(_send_media)
        self.client = client

        async def _amain():
            poll_task = asyncio.create_task(
                poll_loop(backend, client, C.WECHAT_ACCOUNT_ID, poll_sec=C.POLL_SEC))
            try:
                await client.run_forever(stop_event=self.stop_event)
            finally:
                try:
                    if not poll_task.done():
                        poll_task.cancel()
                        try:
                            await poll_task
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                except Exception:
                    pass

        def _thread_main():
            loop = asyncio.new_event_loop()
            self.loop = loop
            asyncio.set_event_loop(loop)
            try:
                self._main_task = loop.create_task(_amain())
                if self.stop_event.is_set():
                    self._main_task.cancel()
                loop.run_until_complete(self._main_task)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                _st.set_field("last_error", str(e)[:300])
                _st.log(f"运行时异常: {e}")
            finally:
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                finally:
                    loop.close()
                    self._main_task = None
                    _st.set_field("running", False)
                    _st.set_field("connected", False)
                    _st.log("采集与网络连接已停止")

        self.thread = threading.Thread(target=_thread_main, daemon=True,
                                       name="txrui-runtime")
        self.thread.start()

    def stop(self) -> bool:
        self.stop_event.set()
        loop = self.loop
        thread = self.thread

        def cancel_tasks():
            # 同时取消采集和连接任务，唤醒正在等待 WebSocket/重连的协程。
            for task in asyncio.all_tasks(loop):
                task.cancel()

        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(cancel_tasks)
            except RuntimeError:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        stopped = thread is None or not thread.is_alive()
        if stopped:
            _st.set_field("running", False)
            _st.set_field("connected", False)
        return stopped

    # ---- GUI 动作 ----
    def test_shot(self) -> str:
        import os
        import time
        from . import capture as _cap
        if self.backend is None or self.backend._hwnd is None:
            return "未连接"
        shot = _cap.capture_window(self.backend._hwnd)
        if shot is None:
            return "截图失败"
        path = os.path.join(os.getcwd(), f"txrui_shot_{int(time.time())}.png")
        shot.convert("RGB").save(path)
        _st.log(f"截图已保存 {path} {shot.size[0]}x{shot.size[1]}")
        return f"{path} {shot.size[0]}x{shot.size[1]}"

    def read_title_now(self) -> str:
        if self.backend is None:
            return "未连接"
        try:
            title = self.backend.read_title(foreground=False)
            _st.log(f"当前标题: {title!r}")
            return title or "(空)"
        except Exception as e:
            return f"失败: {e}"
