"""验证发送日志与回执计数，确保日志不推断服务端授权或存储结果。"""
from __future__ import annotations

import asyncio
import json
import threading

from txrui import state
from txrui.ws_client import TxruiClient


def test_send_log_does_not_claim_authorization_failure(monkeypatch):
    logs = []
    monkeypatch.setattr(state, "log", logs.append)
    monkeypatch.setattr(state, "bump", lambda *args: None)
    stop = threading.Event()
    sent = []

    class WS:
        async def send(self, raw):
            sent.append(json.loads(raw))
            stop.set()

    async def scenario():
        client = TxruiClient("ws://example", "cid", "test-token")
        payload = {"event_id": "evt_test", "chat_id": "测试会话",
                   "chat_type": "private", "client_seq": "123_test"}
        client.queue_event(payload)
        await client._sender_loop(WS(), stop)
        assert sent == [{"type": "event", "payload": payload}]
        assert not client.buffer

    asyncio.run(scenario())
    assert len(logs) == 1
    assert "event=evt_test" in logs[0]
    assert "仅确认发送完成" in logs[0]
    assert "未授权" not in logs[0]
    assert "core" not in logs[0]


def test_ack_log_does_not_claim_core_storage(monkeypatch):
    logs = []
    counts = []
    monkeypatch.setattr(state, "log", logs.append)
    monkeypatch.setattr(state, "bump", counts.append)
    client = TxruiClient("ws://example", "cid", "test-token")
    asyncio.run(client._on_message(None, {"type": "ack", "event_id": "evt_test"}))
    assert counts == ["acked"]
    assert logs == ["收到服务端 ACK event=evt_test"]
