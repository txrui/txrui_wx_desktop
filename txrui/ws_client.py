"""处理 WebSocket 握手、心跳、事件队列、媒体传输和下行操作回执。

所有写帧通过锁串行执行；收帧分派为独立任务，允许发送过程等待媒体回执。
事件队列和下行结果缓存均在内存中；发送完成不等于服务端确认处理。
"""
from __future__ import annotations

import asyncio
import base64
import collections
import inspect
import json
import logging
import time

import websockets

PROTOCOL_VERSION = "1.0"
logger = logging.getLogger(__name__)

#: 单次媒体上传的字节上限。
MAX_MEDIA_BYTES = 20 * 1024 * 1024


class TxruiClient:
    def __init__(self, core_ws_url: str, connector_id: str, token: str,
                 account_ids: str = "", client_info: str = "txrui_desktop/1.0",
                 heartbeat_sec: int = 25, buffer_size: int = 500):
        self.core_ws_url = core_ws_url
        self.connector_id = connector_id
        self.token = token
        self.account_ids = account_ids
        self.client_info = client_info
        self.heartbeat_sec = heartbeat_sec
        self.buffer: collections.deque = collections.deque(maxlen=buffer_size)
        self._send_fn = None
        self._send_media_fn = None
        self._send_mixed_fn = None
        self._recall_fn = None
        # 按请求标识缓存已完成的下行结果，供后续重复请求复用。
        self._seen_outbound: dict[str, dict] = {}
        self._seen_outbound_max = 500
        # 默认能力声明；音频下行固定拒绝，媒体发送依赖已绑定的钩子。
        # 撤回按内容定位，不提供稳定消息标识、历史、编辑或引用能力。
        self.capabilities = {"text": True, "image": True, "file": True,
                             "video": True, "sticker": True, "audio": False,
                             "quote": False, "recall": True, "edit": False,
                             "history": False, "stable_message_id": False}
        # 写锁：并发 send 串行化（websockets 不保证并发写安全）
        self._send_lock = asyncio.Lock()
        # 媒体上传回执：client_seq -> Future
        self._media_pending: dict[str, asyncio.Future] = {}
        self._ws = None
        self._media_seq = 0
        self._reconnect_event = asyncio.Event()

    def bind_sender(self, fn):
        self._send_fn = fn

    def bind_media_sender(self, fn):
        """绑定媒体发送钩子，参数为账号、会话、段类型和媒体段。

        签名含 chat_type 或任意关键字参数时，额外按位置传入会话类型。
        媒体下载和实际发送由钩子负责。
        """
        self._send_media_fn = fn

    def bind_mixed_sender(self, fn):
        """绑定文本与单张图片合并发送钩子。

        Args:
            fn: 异步发送函数，参数为账号、会话、文本、图片段和会话类型。
        """
        self._send_mixed_fn = fn

    def bind_recall(self, fn):
        """保存撤回钩子；当前撤回分派直接调用撤回模块，不使用此钩子。"""
        self._recall_fn = fn

    def queue_event(self, payload: dict) -> None:
        self.buffer.append(payload)
        # 队列仅存内存；容量满时丢弃最早事件，发送完成后出队，不按回执重传。

    async def _send_json(self, ws, obj: dict) -> None:
        """串行化写帧。"""
        async with self._send_lock:
            await ws.send(json.dumps(obj, ensure_ascii=False))

    async def _hello(self, ws) -> None:
        await self._send_json(ws, {"type": "hello", "connector_id": self.connector_id,
                                   "token": self.token, "protocol_version": PROTOCOL_VERSION,
                                   "account_ids": self.account_ids, "client_info": self.client_info,
                                   "capabilities": self.capabilities})
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        ack = json.loads(raw)
        if ack.get("type") != "hello_ack":
            raise RuntimeError(f"hello rejected: {ack}")

    async def upload_media(self, data: bytes, filename: str = "", mime: str = "") -> dict:
        """经媒体上传帧提交字节，按客户端序号等待回执，最长等待三十秒。

        空数据、超限、断线、超时或服务端拒绝均返回失败字典。
        """
        if not data:
            return {"ok": False, "media_id": "", "error": "empty"}
        if len(data) > MAX_MEDIA_BYTES:
            return {"ok": False, "media_id": "", "error": "too_large"}
        ws = self._ws
        if ws is None:
            return {"ok": False, "media_id": "", "error": "not_connected"}
        self._media_seq += 1
        seq = f"m{self._media_seq}_{int(time.time())}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._media_pending[seq] = fut
        try:
            await self._send_json(ws, {
                "type": "media_upload", "client_seq": seq,
                "filename": filename or "media", "mime": mime or "",
                "size": len(data),
                "data_b64": base64.b64encode(data).decode("ascii"),
            })
        except Exception as e:  # noqa: BLE001
            self._media_pending.pop(seq, None)
            return {"ok": False, "media_id": "", "error": f"send_failed:{str(e)[:80]}"}
        try:
            resp = await asyncio.wait_for(asyncio.shield(fut), timeout=30)
        except asyncio.TimeoutError:
            self._media_pending.pop(seq, None)
            return {"ok": False, "media_id": "", "error": "timeout_unknown"}
        except Exception as e:  # noqa: BLE001
            self._media_pending.pop(seq, None)
            return {"ok": False, "media_id": "", "error": f"ack_failed:{str(e)[:80]}"}
        if not resp.get("ok"):
            return {"ok": False, "media_id": "", "error": str(resp.get("error", "rejected"))[:120]}
        return {"ok": True, "media_id": str(resp.get("media_id", "") or ""),
                "mime": str(resp.get("mime", "") or ""),
                "size": int(resp.get("size", 0) or 0)}

    def _resolve_media_ack(self, msg: dict) -> None:
        seq = str(msg.get("client_seq", "") or "")
        fut = self._media_pending.pop(seq, None)
        if fut is None or fut.done():
            return
        fut.set_result({
            "ok": bool(msg.get("ok", False)),
            "media_id": str(msg.get("media_id", "") or ""),
            "mime": str(msg.get("mime", "") or ""),
            "size": int(msg.get("size", 0) or 0),
            "error": str(msg.get("error", "") or ""),
        })

    async def fetch_media(self, media_id: str) -> dict:
        """经已连接的 WebSocket 请求媒体，解码回执中的二进制数据。

        返回数据、文件名、媒体类型和大小；请求或解码失败时返回错误字典。
        本方法不使用 HTTP 下载。
        """
        if not media_id:
            return {"ok": False, "data": b"", "error": "no_media_id"}
        ws = self._ws
        if ws is None:
            return {"ok": False, "data": b"", "error": "not_connected"}
        self._media_seq += 1
        seq = f"f{self._media_seq}_{int(time.time())}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._media_pending[seq] = fut
        try:
            await self._send_json(ws, {
                "type": "media_fetch", "client_seq": seq, "media_id": media_id,
            })
        except Exception as e:  # noqa: BLE001
            self._media_pending.pop(seq, None)
            return {"ok": False, "data": b"", "error": f"send_failed:{str(e)[:80]}"}
        try:
            resp = await asyncio.wait_for(asyncio.shield(fut), timeout=30)
        except asyncio.TimeoutError:
            self._media_pending.pop(seq, None)
            return {"ok": False, "data": b"", "error": "timeout_unknown"}
        except Exception as e:  # noqa: BLE001
            self._media_pending.pop(seq, None)
            return {"ok": False, "data": b"", "error": f"ack_failed:{str(e)[:80]}"}
        if not resp.get("ok"):
            return {"ok": False, "data": b"",
                    "error": str(resp.get("error", "rejected"))[:120]}
        raw = resp.get("data_b64") or ""
        try:
            data = base64.b64decode(raw) if raw else b""
        except Exception:
            return {"ok": False, "data": b"", "error": "bad_base64"}
        if not data:
            return {"ok": False, "data": b"", "error": "empty_blob"}
        return {"ok": True, "data": data,
                "filename": str(resp.get("filename", "") or ""),
                "mime": str(resp.get("mime", "") or ""),
                "size": len(data)}

    def _resolve_media_fetch_ack(self, msg: dict) -> None:
        seq = str(msg.get("client_seq", "") or "")
        fut = self._media_pending.pop(seq, None)
        if fut is None or fut.done():
            return
        fut.set_result({
            "ok": bool(msg.get("ok", False)),
            "media_id": str(msg.get("media_id", "") or ""),
            "mime": str(msg.get("mime", "") or ""),
            "filename": str(msg.get("filename", "") or ""),
            "size": int(msg.get("size", 0) or 0),
            "data_b64": str(msg.get("data_b64", "") or ""),
            "error": str(msg.get("error", "") or ""),
        })

    async def _sender_loop(self, ws, stop_event=None) -> None:
        """持续发送队首事件，写帧成功后出队；失败保留队首并稍后重试。"""
        from . import state as _st
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                if self.buffer:
                    payload = self.buffer[0]  # 先看队首，发成功才 pop，失败留队重试
                    await self._send_json(ws, {"type": "event", "payload": payload})
                    self.buffer.popleft()
                    try:
                        _st.bump("reported")
                        _st.log(f"已发送至服务端 chat={payload.get('chat_id','')} "
                                f"type={payload.get('chat_type','')} "
                                f"seq={payload.get('client_seq','')} "
                                f"event={payload.get('event_id','')} "
                                f"（仅确认发送完成，服务端处理结果以回执或服务端日志为准）")
                    except Exception:
                        pass
                else:
                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                logger.warning(f"上报失败 {e}")
                try:
                    _st.log(f"上报失败: {e}")
                except Exception:
                    pass
                await asyncio.sleep(0.5)

    def request_reconnect(self) -> None:
        """在客户端所属事件循环内调用，打断连接、握手或退避等待。"""
        self._reconnect_event.set()

    async def run_forever(self, stop_event=None) -> None:
        while stop_event is None or not stop_event.is_set():
            self._reconnect_event.clear()
            connection = asyncio.create_task(self._run_connection(stop_event))
            reconnect = asyncio.create_task(self._reconnect_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (connection, reconnect), return_when=asyncio.FIRST_COMPLETED)
                if connection in done:
                    await connection
                    return
            finally:
                connection.cancel()
                reconnect.cancel()
                await asyncio.gather(connection, reconnect, return_exceptions=True)

    async def _run_connection(self, stop_event=None) -> None:
        from . import state as _st
        backoff = 2
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                async with websockets.connect(self.core_ws_url, max_size=64 * 1024 * 1024) as ws:
                    await self._hello(ws)
                    self._ws = ws
                    _st.set_field("connected", True)
                    _st.log("WS 已连接 (hello_ack)")
                    backoff = 2
                    hb = asyncio.create_task(self._heartbeat(ws, stop_event))
                    sender = asyncio.create_task(self._sender_loop(ws, stop_event))
                    # 处理 outbound 的任务集合：帧处理必须**并发**进行，
                    # 否则发消息时会在 `_on_message` 里 await `fetch_media`，
                    # 而 `media_fetch_ack` 要等这个循环再读一帧才能拿到 —— 死锁。
                    handlers: set[asyncio.Task] = set()
                    try:
                        async for raw in ws:
                            if stop_event is not None and stop_event.is_set():
                                return
                            try:
                                msg = json.loads(raw)
                            except ValueError:
                                continue
                            # 每个帧单独起任务处理：读循环不被慢帧阻塞，
                            # `media_fetch_ack` 能在 outbound 处理期间被读到。
                            task = asyncio.create_task(self._on_message(ws, msg))
                            handlers.add(task)
                            task.add_done_callback(handlers.discard)
                    finally:
                        pending_handlers = list(handlers)
                        for task in pending_handlers:
                            task.cancel()
                        hb.cancel()
                        sender.cancel()
                        await asyncio.gather(hb, sender, *pending_handlers,
                                             return_exceptions=True)
                        self._ws = None
                        # 断线时把未决的上传回执全部判失败，调用方降级为占位
                        for fut in list(self._media_pending.values()):
                            if not fut.done():
                                fut.set_result({"ok": False, "media_id": "",
                                                "error": "disconnected"})
                        self._media_pending.clear()
                        _st.set_field("connected", False)
            except Exception as e:
                self._ws = None
                _st.set_field("connected", False)
                logger.warning(f"连接中断 {e}，{backoff}s 后重连")
                _st.log(f"连接中断 {e}，{backoff}s 后重连")
                for _ in range(int(backoff * 2)):
                    if stop_event is not None and stop_event.is_set():
                        return
                    await asyncio.sleep(0.5)
                backoff = min(backoff * 2, 60)

    async def _heartbeat(self, ws, stop_event=None) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_sec)
            if stop_event is not None and stop_event.is_set():
                return
            try:
                await self._send_json(ws, {"type": "heartbeat",
                                           "connector_id": self.connector_id,
                                           "ts": int(time.time())})
            except Exception:
                return

    async def _on_message(self, ws, msg: dict) -> None:
        mtype = msg.get("type", "")
        if mtype in ("heartbeat_ack",):
            return
        if mtype == "media_ack":
            self._resolve_media_ack(msg)
            return
        if mtype == "media_fetch_ack":
            self._resolve_media_fetch_ack(msg)
            return
        if mtype == "ack":
            # 仅确认服务端接收/入队，不表示机器人处理或回复完成。
            from . import state as _st
            ok = msg.get("ok", True)  # 兼容没有 ok/status 字段的旧 core 回执。
            if ok:
                _st.bump("acked")
            try:
                if "status" in msg or not ok:
                    _st.log(f"服务端事件回执 event={msg.get('event_id','')} "
                            f"ok={bool(ok)} status={msg.get('status','')} "
                            f"error={msg.get('error','')}")
                else:
                    _st.log(f"收到服务端 ACK event={msg.get('event_id','')}")
            except Exception:
                pass
            return
        if mtype != "outbound":
            return
        rid = msg.get("request_id", "")
        # 命中已完成请求的缓存时直接回执；并发中的同标识请求不在此拦截。
        if rid and rid in self._seen_outbound:
            await self._send_json(ws, {"type": "send_ack", "request_id": rid,
                                       **self._seen_outbound[rid]})
            return
        payload = msg.get("payload", {})
        from . import state as _st
        _st.push_down_event(payload)
        action = str(payload.get("action", "message.send") or "message.send")
        if action == "message.recall":
            result = await self._do_recall(payload)
            self._remember_outbound(rid, result)
            await self._send_json(ws, {"type": "send_ack", "request_id": rid, **result})
            return
        if self._send_fn is None:
            result = {"ok": False, "unknown": True, "platform_message_id": "",
                      "error": "no_sender_bound"}
        else:
            try:
                result = await self._dispatch_send(payload)
            except Exception as e:
                result = {"ok": False, "unknown": True, "platform_message_id": "",
                          "error": f"send_exception:{e}"[:200]}
        self._remember_outbound(rid, result)
        await self._send_json(ws, {"type": "send_ack", "request_id": rid, **result})

    async def _do_recall(self, payload: dict) -> dict:
        """从当前运行时取得后端，按下行目标文本在当前会话尝试撤回。

        不按账号、会话或平台消息标识定位；缺少后端或目标文本时返回失败。
        """
        account_id = str(payload.get("account_id", "") or "")
        chat_id = str(payload.get("chat_id", "") or "")
        pmid = str(payload.get("platform_message_id", "") or "")
        target = str(payload.get("text", "") or payload.get("target_text", "") or "")
        try:
            from . import recall as _recall
            from . import runtime as _rt
            backend = _rt.current_backend()
            if backend is None:
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": "no_backend:未连接微信窗口"}
            if not target:
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": "no_target_text:撤回需按消息内容定位"}
            res = _recall.recall_message(backend._hwnd, target_text=target)
            return res
        except Exception as e:  # noqa: BLE001
            logger.warning(f"撤回处理失败: {e}")
            return {"ok": False, "unknown": True, "platform_message_id": "",
                    "error": f"recall_exception:{str(e)[:120]}"}

    async def _call_send_fn(self, account_id: str, chat_id: str, text: str,
                            chat_type: str = "") -> dict:
        """探测文本钩子签名，按三个参数或附加会话类型的四个参数调用。"""
        fn = self._send_fn
        if fn is None:
            return {"ok": False, "unknown": True, "platform_message_id": "",
                    "error": "no_sender_bound"}
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        accepts_type = "chat_type" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_type:
            return await fn(account_id, chat_id, text, chat_type)
        return await fn(account_id, chat_id, text)

    async def _dispatch_send(self, payload: dict) -> dict:
        """按顺序发送内容段，任一段失败立即返回，不回滚此前已完成的发送。

        文本、引用和系统段使用文本钩子；音频直接拒绝，其余类型交给媒体钩子。
        忽略非字典段和空文本；没有实际发送内容时返回失败。
        """
        account_id = str(payload.get("account_id", "") or "")
        chat_id = str(payload.get("chat_id", "") or "")
        # core 下行可能带 chat_type（private/group），缺失时按 unknown 处理，
        # 由发送侧自己判定目标会话类型，不在此处臆断。
        chat_type = str(payload.get("chat_type", "") or "").strip().lower()
        if chat_type not in ("private", "group"):
            chat_type = ""
        content = payload.get("content") or []
        # 字符串内容包装为单个文本段。
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list) or not content:
            return {"ok": False, "unknown": False, "platform_message_id": "",
                    "error": "empty_content"}
        if self._send_mixed_fn is not None:
            text_parts = []
            image_segment = None
            can_merge = True
            for segment in content:
                if not isinstance(segment, dict):
                    can_merge = False
                    break
                segment_type = str(segment.get("type", "text") or "text").lower()
                if segment_type in ("text", "quote", "system") and image_segment is None:
                    text = str(segment.get("text", "") or "")
                    if text:
                        text_parts.append(text)
                elif segment_type == "image" and image_segment is None:
                    image_segment = segment
                else:
                    can_merge = False
                    break
            if can_merge and text_parts and image_segment is not None:
                return await self._call_mixed_sender(
                    account_id, chat_id, "".join(text_parts), image_segment, chat_type
                )
        # _send_fn 绑定的是 (account_id, chat_id, text) -> dict
        # 多段时需要媒体发送能力，用 send_fn 之外的扩展钩子。
        sender_ext = getattr(self, "_send_media_fn", None)
        sent_any = False
        last = {"ok": False, "unknown": True, "platform_message_id": "", "error": ""}
        for c in content:
            if not isinstance(c, dict):
                continue
            ctype = str(c.get("type", "text") or "text").lower()
            text = str(c.get("text", "") or "")
            if ctype in ("text", "quote", "system"):
                if not text:
                    continue
                result = await self._call_send_fn(account_id, chat_id, text, chat_type)
                if not result.get("ok"):
                    return result
                sent_any = True
                last = result
                continue
            if ctype == "audio":
                # 协议下行固定不支持音频，与本地可选语音通道的可用性无关。
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": "audio_unsupported:微信视觉端不支持发真语音消息"}
            # image / file / video / sticker：走媒体发送钩子
            if sender_ext is None:
                return {"ok": False, "unknown": False, "platform_message_id": "",
                        "error": f"{ctype}_unsupported:未绑定媒体发送能力"}
            try:
                result = await self._call_media_sender(account_id, chat_id, ctype,
                                                      c, chat_type)
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "unknown": True, "platform_message_id": "",
                        "error": f"{ctype}_send_exception:{str(e)[:120]}"}
            if not result.get("ok"):
                return result
            sent_any = True
            last = result
        if not sent_any:
            return {"ok": False, "unknown": False, "platform_message_id": "",
                    "error": "nothing_to_send"}
        return last

    async def _call_mixed_sender(self, account_id: str, chat_id: str, text: str,
                                 segment: dict, chat_type: str = "") -> dict:
        """Call the mixed sender with or without the optional chat type."""
        fn = self._send_mixed_fn
        if fn is None:
            return {"ok": False, "unknown": False, "platform_message_id": "",
                    "error": "mixed_unsupported:no_mixed_sender"}
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        accepts_type = "chat_type" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_type:
            return await fn(account_id, chat_id, text, segment, chat_type)
        return await fn(account_id, chat_id, text, segment)

    async def _call_media_sender(self, account_id: str, chat_id: str, seg_type: str,
                                 segment: dict, chat_type: str = "") -> dict:
        """探测媒体钩子签名，按四个参数或附加会话类型的五个参数调用。"""
        fn = self._send_media_fn
        if fn is None:
            return {"ok": False, "unknown": False, "platform_message_id": "",
                    "error": "media_unsupported:未绑定媒体发送能力"}
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            params = {}
        accepts_type = "chat_type" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if accepts_type:
            return await fn(account_id, chat_id, seg_type, segment, chat_type)
        return await fn(account_id, chat_id, seg_type, segment)

    def _remember_outbound(self, rid: str, result: dict) -> None:
        if not rid:
            return
        try:
            self._seen_outbound[rid] = dict(result)
            while len(self._seen_outbound) > self._seen_outbound_max:
                self._seen_outbound.pop(next(iter(self._seen_outbound)))
        except Exception:
            pass
