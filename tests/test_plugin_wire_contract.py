"""直接使用插件服务端和桌面客户端验证协议，不依赖 AstrBot 或微信。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_txrui.txrui_client import TxruiConnection, TxruiWSServer
from txrui import state
from txrui.payload import message_to_payload
from txrui.ws_client import TxruiClient


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def test_account_routing_is_exact_and_never_falls_back(tmp_path):
    server = TxruiWSServer(media_dir=tmp_path)
    first = TxruiConnection(FakeWS(), "cid", "wx_001")
    second = TxruiConnection(FakeWS(), "cid", "wx_001_extra,wx_002")
    second.connected_at = first.connected_at + 1
    server._connections.update(a=first, b=second)
    assert server.find_connection("same-group", "wx_001") is first
    assert server.find_connection("same-group", "wx_002") is second
    assert server.find_connection("wx_001_extra", "missing") is None
    assert server.find_connection("wx_001_extra") is first  # 默认账号，不按群名匹配。
    newer = TxruiConnection(FakeWS(), "cid", "wx_001")
    newer.connected_at = second.connected_at + 1
    server._connections["c"] = newer
    assert server.find_connection("group", "wx_001") is newer


def test_legacy_accountless_connection_is_only_used_when_unambiguous(tmp_path):
    server = TxruiWSServer(media_dir=tmp_path)
    conn = TxruiConnection(FakeWS(), "cid")
    server._connections["a"] = conn
    assert server.find_connection("group") is conn
    assert server.find_connection("group", "other") is None
    server._connections["b"] = TxruiConnection(FakeWS(), "cid", "other")
    assert server.find_connection("group") is None


@pytest.mark.parametrize("result", [
    {"ok": True, "status": "queued", "error": ""},
    {"ok": True, "status": "filtered", "error": ""},
    {"ok": False, "status": "rejected", "error": "invalid_message"},
])
def test_event_ack_preserves_callback_status(tmp_path, result):
    async def scenario():
        server = TxruiWSServer(media_dir=tmp_path, on_event=AsyncMock(return_value=result))
        conn = TxruiConnection(FakeWS(), "cid", "wx_001")
        await server._handle_event(conn, {"payload": {"event_id": "e1", "client_seq": "s1"}})
        assert conn.ws.sent == [{"type": "ack", "event_id": "e1", "client_seq": "s1", **result}]
    asyncio.run(scenario())


def test_event_ack_reports_handler_failure_and_invalid_payload(tmp_path):
    async def scenario():
        server = TxruiWSServer(media_dir=tmp_path, on_event=AsyncMock(side_effect=RuntimeError("failed")))
        conn = TxruiConnection(FakeWS(), "cid", "wx_001")
        await server._handle_event(conn, {"payload": {"event_id": "e1"}})
        assert conn.ws.sent[-1]["ok"] is False
        assert conn.ws.sent[-1]["status"] == "failed"
        await server._handle_event(conn, {"payload": []})
        assert conn.ws.sent[-1]["error"] == "invalid_payload"
    asyncio.run(scenario())


def test_failed_event_ack_does_not_increment_success(monkeypatch):
    counts, logs = [], []
    monkeypatch.setattr(state, "bump", counts.append)
    monkeypatch.setattr(state, "log", logs.append)
    client = TxruiClient("ws://unused", "cid", "tok")
    asyncio.run(client._on_message(None, {"type": "ack", "event_id": "e1", "ok": False,
                                         "status": "failed", "error": "conversion_failed"}))
    assert counts == []
    assert "conversion_failed" in logs[0]


def test_real_websocket_group_reply_media_and_multi_account(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "log", lambda *args: None)
    monkeypatch.setattr(state, "bump", lambda *args: None)

    async def scenario():
        events, sent = [], []
        ack_seen = asyncio.Event()

        async def on_event(payload, conn):
            events.append(payload)
            return {"ok": True, "status": "queued", "error": ""}

        server = TxruiWSServer(host="127.0.0.1", port=0, token="test-only", media_dir=tmp_path, on_event=on_event)
        await server.start()
        port = server._server.sockets[0].getsockname()[1]
        clients, sockets, readers, handlers = [], [], [], set()

        async def read_loop(ws, client):
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "ack":
                    assert msg["ok"] and msg["status"] == "queued"
                    ack_seen.set()
                task = asyncio.create_task(client._on_message(ws, msg))
                handlers.add(task)
                task.add_done_callback(handlers.discard)

        try:
            for account in ("wx_001", "wx_001_extra"):
                client = TxruiClient(f"ws://127.0.0.1:{port}", "txrui_001", "test-only", account_ids=account)
                ws = await websockets.connect(client.core_ws_url)
                sockets.append(ws)
                await client._hello(ws)
                client._ws = ws

                async def send_text(account_id, chat_id, text, chat_type="", owner=account):
                    sent.append((owner, account_id, chat_id, text, chat_type))
                    return {"ok": True, "unknown": False}

                async def send_media(account_id, chat_id, kind, segment, chat_type="", owner=account, active=client):
                    media = await active.fetch_media(segment["media_id"])
                    assert media["data"] == b"image-bytes"
                    sent.append((owner, account_id, chat_id, kind, chat_type))
                    return {"ok": True, "unknown": False}

                client.bind_sender(send_text)
                client.bind_media_sender(send_media)
                clients.append(client)
                readers.append(asyncio.create_task(read_loop(ws, client)))

            payload = message_to_payload("wx_001", "same-group", "member", "hello", chat_type="group")
            await clients[0]._send_json(sockets[0], {"type": "event", "payload": payload})
            await asyncio.wait_for(ack_seen.wait(), 2)
            assert events == [payload]
            up = await clients[0].upload_media(b"image-bytes", "a.png", "image/png")
            assert up["ok"]
            first = await server.send_outbound("same-group", [{"type": "text", "text": "reply"}], account_id="wx_001", chat_type="group")
            assert first["ok"]
            second = await server.send_outbound("same-group", [{"type": "image", "media_id": up["media_id"]}], account_id="wx_001_extra", chat_type="private")
            assert second["ok"]
            assert sent == [("wx_001", "wx_001", "same-group", "reply", "group"),
                            ("wx_001_extra", "wx_001_extra", "same-group", "image", "private")]
            missing = await server.send_outbound("same-group", [{"type": "text", "text": "x"}], account_id="wx_missing")
            assert missing["error"] == "no_connection"
        finally:
            for ws in sockets:
                await ws.close()
            for task in readers + list(handlers):
                task.cancel()
            await asyncio.gather(*readers, *list(handlers), return_exceptions=True)
            await server.stop()

    asyncio.run(asyncio.wait_for(scenario(), 10))
