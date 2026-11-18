"""下报摘要和立即重连的回归测试。"""
import asyncio
import collections
import json

import pytest

from txrui import state
from txrui.runtime import Runtime
from txrui.webbridge import TxruiBridge
from txrui.ws_client import TxruiClient


def test_down_events_recent_first_and_media_summary(monkeypatch):
    monkeypatch.setattr(state, "_down_events", collections.deque(maxlen=100))
    state.push_down_event({"chat_id": "张三", "chat_type": "private", "content": "你好"})
    state.push_down_event({"chat_id": "测试群", "chat_type": "group", "content": [
        {"type": "text", "text": "图片"}, {"type": "image", "data_b64": "secret"}]})
    events = state.get_down_events(30)
    assert events[0]["text"] == "图片 [image]"
    assert events[0]["chat_type"] == "group"
    assert events[1]["text"] == "你好"
    assert "secret" not in str(events)
    assert TxruiBridge(None).get_status()["down_events"] == events


def test_outbound_records_before_send_and_ignores_cached_duplicates(monkeypatch):
    records = []
    monkeypatch.setattr(state, "push_down_event", records.append)

    class WS:
        async def send(self, raw):
            assert json.loads(raw)["type"] == "send_ack"

    async def scenario():
        client = TxruiClient("ws://example", "cid", "token")
        payload = {"chat_id": "张三", "content": "你好"}
        msg = {"type": "outbound", "request_id": "request-1", "payload": payload}
        await client._on_message(WS(), msg)
        await client._on_message(WS(), msg)
        assert records == [payload]
    asyncio.run(scenario())


def test_reconnect_interrupts_wait_without_losing_queue(monkeypatch):
    async def scenario():
        client = TxruiClient("ws://example", "cid", "token")
        client.queue_event({"event_id": "queued"})
        started = asyncio.Queue()
        cleaned = []

        async def connection(stop_event=None):
            await started.put(True)
            try:
                # 模拟连接、握手或退避中的无限等待。
                await asyncio.Event().wait()
            finally:
                cleaned.append(True)

        monkeypatch.setattr(client, "_run_connection", connection)
        task = asyncio.create_task(client.run_forever())
        try:
            await asyncio.wait_for(started.get(), 1)
            client.request_reconnect()
            await asyncio.wait_for(started.get(), 1)
            assert cleaned == [True]
            assert list(client.buffer) == [{"event_id": "queued"}]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert cleaned == [True, True]
    asyncio.run(scenario())


def test_reconnect_stopped_runtime_returns_clear_error():
    result = TxruiBridge(Runtime()).runtime_reconnect()
    assert result["ok"] is False
    assert "请先启动采集" in result["error"]
