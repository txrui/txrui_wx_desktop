"""验证 WebSocket 下行分派、会话类型传递、媒体取回和能力声明。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from txrui.ws_client import TxruiClient


def _run(coro):
    return asyncio.run(coro)


class _FakeWS:
    """最小 WebSocket 替身：记录发出的帧，可预置回执。"""

    def __init__(self, replies=None):
        self.sent: list[dict] = []
        self._replies = list(replies or [])
        self._i = 0

    async def send(self, raw: str):
        import json
        self.sent.append(json.loads(raw))

    async def recv(self):
        if self._i >= len(self._replies):
            raise RuntimeError("eof")
        r = self._replies[self._i]
        self._i += 1
        import json
        return json.dumps(r)


def _client():
    c = TxruiClient("ws://x", "cid", "tok")
    return c


class TestDispatchSend:
    def test_text_segment(self):
        async def scenario():
            c = _client()
            calls = []

            async def _send(a, ch, t):
                calls.append((a, ch, t))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "1", "error": ""}

            c.bind_sender(_send)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "text", "text": "你好"}]})
            assert r["ok"] is True
            assert calls == [("wx1", "张三", "你好")]
        _run(scenario())

    def test_media_segment_dispatches_to_media_hook(self):
        async def scenario():
            c = _client()
            seen = []

            async def _send(a, ch, t):
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            async def _media(a, ch, stype, seg):
                seen.append((stype, seg.get("media_id")))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            c.bind_sender(_send)
            c.bind_media_sender(_media)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "image", "media_id": "mb_1",
                             "url": "/api/v1/media/blobs/mb_1"}]})
            assert r["ok"] is True
            assert seen == [("image", "mb_1")]
        _run(scenario())

    def test_mixed_text_and_media(self):
        async def scenario():
            c = _client()
            order = []

            async def _send(a, ch, t):
                order.append(("text", t))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            async def _media(a, ch, stype, seg):
                order.append(("media", stype))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            c.bind_sender(_send)
            c.bind_media_sender(_media)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "text", "text": "看这个"},
                            {"type": "image", "media_id": "mb_1"}]})
            assert r["ok"] is True
            assert order == [("text", "看这个"), ("media", "image")]
        _run(scenario())

    def test_audio_fails_honestly(self):
        """未绑定语音发送能力时，音频段返回不支持错误。"""
        async def scenario():
            c = _client()

            async def _send(a, ch, t):
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            c.bind_sender(_send)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "audio", "text": "[语音]"}]})
            assert r["ok"] is False
            assert "audio_unsupported" in r["error"]
        _run(scenario())

    def test_media_failure_fails_whole_message(self):
        """任一媒体段发送失败时，整个消息返回失败。"""
        async def scenario():
            c = _client()

            async def _send(a, ch, t):
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            async def _media(a, ch, stype, seg):
                return {"ok": False, "unknown": False,
                        "platform_message_id": "", "error": "blob_fetch_failed"}

            c.bind_sender(_send)
            c.bind_media_sender(_media)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "text", "text": "x"},
                            {"type": "file", "media_id": "mb_2"}]})
            assert r["ok"] is False
            assert r["error"] == "blob_fetch_failed"
        _run(scenario())

    def test_no_media_hook_is_unsupported(self):
        async def scenario():
            c = _client()

            async def _send(a, ch, t):
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            c.bind_sender(_send)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "image", "media_id": "mb_1"}]})
            assert r["ok"] is False
            assert "unsupported" in r["error"]
        _run(scenario())

    def test_empty_content_fails(self):
        async def scenario():
            c = _client()
            r = await c._dispatch_send({"account_id": "wx1", "chat_id": "x",
                                         "content": []})
            assert r["ok"] is False
            assert r["error"] == "empty_content"
        _run(scenario())

    def test_string_content_compat(self):
        """字符串形式的内容按文本段发送。"""
        async def scenario():
            c = _client()
            calls = []

            async def _send(a, ch, t):
                calls.append(t)
                return {"ok": True, "unknown": False,
                        "platform_message_id": "", "error": ""}

            c.bind_sender(_send)
            r = await c._dispatch_send({"account_id": "wx1", "chat_id": "x",
                                         "content": "直接字符串"})
            assert r["ok"] is True
            assert calls == ["直接字符串"]
        _run(scenario())


class TestChatTypePassthrough:
    """验证下行会话类型传入文本和媒体发送回调。"""

    def test_chat_type_passed_to_new_style_sender(self):
        async def scenario():
            c = _client()
            calls = []

            async def _send(a, ch, t, chat_type=""):
                calls.append((a, ch, t, chat_type))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "1", "error": ""}

            c.bind_sender(_send)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "摸鱼集团(5)",
                "chat_type": "group",
                "content": [{"type": "text", "text": "你好"}]})
            assert r["ok"] is True
            assert calls == [("wx1", "摸鱼集团(5)", "你好", "group")]
        _run(scenario())

    def test_old_style_sender_still_works(self):
        """三参数发送回调仍可处理带会话类型的消息。"""
        async def scenario():
            c = _client()
            calls = []

            async def _send(a, ch, t):
                calls.append((a, ch, t))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "1", "error": ""}

            c.bind_sender(_send)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "chat_type": "private",
                "content": [{"type": "text", "text": "你好"}]})
            assert r["ok"] is True
            assert calls == [("wx1", "张三", "你好")]
        _run(scenario())

    def test_chat_type_passed_to_media_sender(self):
        async def scenario():
            c = _client()
            calls = []

            async def _send_media(a, ch, st, seg, chat_type=""):
                calls.append((a, ch, st, chat_type))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "1", "error": ""}

            c.bind_media_sender(_send_media)
            r = await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "chat_type": "private",
                "content": [{"type": "image", "text": "a.png",
                             "media_id": "mb_1"}]})
            assert r["ok"] is True
            assert calls == [("wx1", "张三", "image", "private")]
        _run(scenario())

    def test_missing_chat_type_passes_empty_string(self):
        async def scenario():
            c = _client()
            calls = []

            async def _send(a, ch, t, chat_type=""):
                calls.append((a, ch, t, chat_type))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "1", "error": ""}

            c.bind_sender(_send)
            await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "content": [{"type": "text", "text": "你好"}]})
            assert calls == [("wx1", "张三", "你好", "")]
        _run(scenario())

    def test_invalid_chat_type_normalized_to_empty(self):
        async def scenario():
            c = _client()
            calls = []

            async def _send(a, ch, t, chat_type=""):
                calls.append((a, ch, t, chat_type))
                return {"ok": True, "unknown": False,
                        "platform_message_id": "1", "error": ""}

            c.bind_sender(_send)
            await c._dispatch_send({
                "account_id": "wx1", "chat_id": "张三",
                "chat_type": "WEIRD",
                "content": [{"type": "text", "text": "你好"}]})
            assert calls == [("wx1", "张三", "你好", "")]
        _run(scenario())


class TestFetchMedia:
    def test_fetch_media_success(self):
        async def scenario():
            import base64
            c = _client()
            ws = _FakeWS()
            c._ws = ws
            # 模拟服务端返回与请求序号对应的媒体回执。
            payload = b"\x89PNG-bytes"

            async def _responder():
                await asyncio.sleep(0.05)
                c._resolve_media_fetch_ack({
                    "client_seq": ws.sent[0]["client_seq"],
                    "ok": True, "media_id": "mb_1", "mime": "image/png",
                    "filename": "pic.png", "size": len(payload),
                    "data_b64": base64.b64encode(payload).decode()})

            task = asyncio.create_task(_responder())
            r = await c.fetch_media("mb_1")
            await task
            assert r["ok"] is True
            assert r["data"] == payload
            assert r["filename"] == "pic.png"
        _run(scenario())

    def test_fetch_media_rejected(self):
        async def scenario():
            c = _client()
            ws = _FakeWS()
            c._ws = ws

            async def _responder():
                await asyncio.sleep(0.05)
                c._resolve_media_fetch_ack({
                    "client_seq": ws.sent[0]["client_seq"],
                    "ok": False, "error": "not_found"})

            task = asyncio.create_task(_responder())
            r = await c.fetch_media("mb_x")
            await task
            assert r["ok"] is False
            assert r["error"] == "not_found"
            assert r["data"] == b""
        _run(scenario())

    def test_fetch_media_not_connected(self):
        async def scenario():
            c = _client()
            r = await c.fetch_media("mb_1")
            assert r["ok"] is False
            assert r["error"] == "not_connected"
        _run(scenario())

    def test_fetch_media_no_id(self):
        async def scenario():
            c = _client()
            r = await c.fetch_media("")
            assert r["ok"] is False
            assert r["error"] == "no_media_id"
        _run(scenario())


class TestCapabilities:
    def test_capabilities_are_honest(self):
        c = _client()
        caps = c.capabilities
        # 默认声明支持的发送类型与撤回操作。
        assert caps["text"] is True
        assert caps["image"] is True
        assert caps["file"] is True
        assert caps["video"] is True
        assert caps["sticker"] is True
        assert caps["recall"] is True
        # 默认声明不支持原生语音发送。
        assert caps["audio"] is False
        # 默认声明不提供稳定消息标识。
        assert caps["stable_message_id"] is False

    def test_caps_are_json_serializable(self):
        import json
        c = _client()
        s = json.dumps(c.capabilities)
        assert '"text": true' in s


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
