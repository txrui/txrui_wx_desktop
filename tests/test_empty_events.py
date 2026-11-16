"""验证空消息在构建、采集和记录时被跳过，纯媒体消息保留占位摘要。"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui import collector, state
from txrui.payload import message_to_payload, event_preview


@pytest.mark.parametrize("text", ["", " \n\t", "\u200b\ufeff\u2060", "　"])
def test_payload_rejects_empty_text(text):
    with pytest.raises(ValueError, match="空消息"):
        message_to_payload("account", "chat", "other", text)


def test_payload_rejects_empty_segments():
    with pytest.raises(ValueError):
        message_to_payload("account", "chat", "other", "", media_segments=[{"type":"text","text":" "}])


@pytest.mark.parametrize("kind,label", [("image","[图片]"),("emoji","[表情]"),("audio","[语音]"),("file","[文件]"),("video","[视频]")])
def test_media_preview_not_empty(kind,label):
    payload=message_to_payload("account","chat","other","",msg_type=kind)
    assert event_preview("",payload["content"])==label


@pytest.mark.parametrize("text,media", [
    ("", []), (" \n", []), ("\u200b\ufeff", []),
    ("", [{}]), ("", [{"kind":"image","w":0,"h":20}]),
    ("", [{"kind":"image","w":float("nan"),"h":20}]),
    ("", [{"kind":"unknown","w":20,"h":20}]),
])
def test_collector_skips_empty_before_upload_and_dedup(text,media):
    backend=Mock(_current_title="测试会话",_current_is_group=False)
    backend.iter_unread_sessions.return_value=[(1,2)]
    backend.get_messages.return_value=[dict(content=text,media=media,sender="other",type="text")]
    client,dedup=Mock(),Mock()
    with patch.object(collector,"_upload_bubbles",new_callable=AsyncMock) as upload, \
         patch.object(state,"push_event") as push:
        assert asyncio.run(collector.poll_once(backend,client,"account",dedup))==0
        upload.assert_not_called()
        dedup.check.assert_not_called()
        client.queue_event.assert_not_called()
        push.assert_not_called()


def test_collector_keeps_media_and_displays_placeholder():
    backend=Mock(_current_title="测试会话",_current_is_group=False)
    backend.iter_unread_sessions.return_value=[(1,2)]
    backend.get_messages.return_value=[dict(content="",media=[dict(kind="image",w=50,h=50)],sender="other",type="image")]
    client,dedup=Mock(),Mock()
    dedup.check.return_value=(False,"",{})
    dedup.snapshot_sequences.return_value=["ocr_test_media"]
    with patch.object(collector,"_upload_bubbles",new_callable=AsyncMock,return_value=[dict(type="image",text="[图片]",extra={"placeholder":True})]), \
         patch.object(state,"push_event") as push:
        assert asyncio.run(collector.poll_once(backend,client,"account",dedup))==1
        client.queue_event.assert_called_once()
        assert push.call_args.args[2]=="[图片]"


def test_state_ignores_empty_without_incrementing_counts():
    before=state.snapshot()
    events=state.get_events(100)
    state.push_event("chat","sender"," \u200b\ufeff\n")
    after=state.snapshot()
    assert after["counts"]["events"]==before["counts"]["events"]
    assert after["last_event_ts"]==before["last_event_ts"]
    assert state.get_events(100)==events
