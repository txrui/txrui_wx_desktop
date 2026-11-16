"""验证滚动、OCR 漏行和媒体重读不会重复上报，真实重复消息仍保留。"""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from txrui import collector, state
from txrui.dedup import OcrDedup


def message(text="收到", y=100, sender="张三", media=None):
    return dict(content=text, y=y, sender=sender,
                type="image" if media else "text", media=media or [])


def collect_frames(frames, *, upload=None, dedup=None):
    backend = Mock(_current_title="测试群(3)", _current_is_group=True)
    backend.iter_unread_sessions.return_value = [(1, 2)]
    backend.get_messages.side_effect = frames
    client = Mock(connector_id="test")
    dedup = dedup or OcrDedup()

    async def scenario():
        counts = []
        with patch.object(state, "push_event"), patch.object(state, "bump"), \
                patch.object(collector, "_upload_bubbles", upload or AsyncMock()) as grab:
            for _ in frames:
                counts.append(await collector.poll_once(backend, client, "account", dedup))
        return counts, grab

    counts, grab = asyncio.run(scenario())
    return counts, [call.args[0] for call in client.queue_event.call_args_list], grab


def test_scroll_and_small_position_jitter_do_not_repeat():
    counts, events, _ = collect_frames([
        [message("第一条", 120), message("第二条", 180)],
        [message("第一条", 118), message("第二条", 178)],
        [message("第一条", 60), message("第二条", 120), message("第三条", 180)],
        [message("第二条", 60), message("第三条", 120), message("第四条", 180)],
    ])
    assert counts == [2, 0, 1, 1]
    assert [e["content"][0]["text"] for e in events] == ["第一条", "第二条", "第三条", "第四条"]
    assert len({e["client_seq"] for e in events}) == 4


def test_distinct_repeated_bubbles_and_senders_are_preserved():
    counts, events, _ = collect_frames([
        [message(y=100), message(y=160)],
        [message(y=40), message(y=100), message(y=160)],
        [message(y=40), message(y=100), message(y=160), message(y=220, sender="李四")],
    ])
    assert counts == [2, 1, 1]
    assert len({e["client_seq"] for e in events}) == 4
    assert events[-1]["sender"]["display_name"] == "李四"


def test_slash_command_is_not_fuzzily_collapsed_with_plain_text():
    counts, _, _ = collect_frames([
        [message("发个表情", 100), message("/发个表情", 160)],
        [message("发个表情", 40), message("/发个表情", 100)],
    ])
    assert counts == [2, 0]


def test_temporary_missing_row_or_empty_frame_does_not_reintroduce_history():
    a, b, c = message("甲", 100), message("乙", 160), message("丙", 220)
    counts, _, _ = collect_frames([[a, b, c], [a, c], [], [a, b, c]])
    assert counts == [3, 0, 0, 0]


def test_revisiting_shorter_history_with_repeated_text_does_not_repeat():
    counts, _, _ = collect_frames([
        [message("甲", 100), message("乙", 160)],
        [message("甲", 40), message("乙", 100), message("甲", 160)],
        [message("甲", 100), message("乙", 160)],
    ])
    assert counts == [2, 1, 0]


def test_same_text_at_reused_position_is_new_when_context_changes():
    counts, events, _ = collect_frames([
        [message("收到", 100), message("旧消息", 160)],
        [message("旧消息", 40), message("新消息", 70), message("收到", 100)],
    ])
    assert counts == [2, 2]
    assert [e["content"][0]["text"] for e in events] == ["收到", "旧消息", "新消息", "收到"]
    assert events[0]["client_seq"] != events[-1]["client_seq"]
    assert events[0]["fingerprint"] != events[-1]["fingerprint"]


def test_media_is_deduplicated_before_upload():
    bubble = dict(kind="image", x=40, y=100, w=80, h=80)
    moved = dict(bubble, y=40)
    upload = AsyncMock(side_effect=[
        [dict(type="image", media_id="first", text="[图片]")],
        [dict(type="image", media_id="second", text="[图片]")],
    ])
    counts, events, grab = collect_frames([
        [message("", 100, media=[bubble])],
        [message("", 40, media=[moved])],
        [message("", 40, media=[moved]), message("", 100, media=[bubble])],
    ], upload=upload)
    assert counts == [1, 0, 1]
    assert grab.await_count == 2
    assert [e["content"][0]["media_id"] for e in events] == ["first", "second"]


def test_upload_failure_can_be_retried_with_same_snapshot():
    backend = Mock(_current_title="测试群(3)", _current_is_group=True)
    backend.iter_unread_sessions.return_value = [(1, 2)]
    backend.get_messages.return_value = [message("", media=[dict(kind="image", w=80, h=80)])]
    client, dedup = Mock(connector_id="test"), OcrDedup()

    async def scenario():
        with patch.object(state, "push_event"), \
                patch.object(collector, "_upload_bubbles", new_callable=AsyncMock) as upload:
            upload.side_effect = RuntimeError("temporary upload failure")
            with pytest.raises(RuntimeError):
                await collector.poll_once(backend, client, "account", dedup)
            upload.side_effect = None
            upload.return_value = [dict(type="image", media_id="retry", text="[图片]")]
            assert await collector.poll_once(backend, client, "account", dedup) == 1
            assert await collector.poll_once(backend, client, "account", dedup) == 0
    asyncio.run(scenario())
    client.queue_event.assert_called_once()


def test_check_preflight_does_not_commit_and_legacy_records_expire():
    dedup = OcrDedup(window_sec=10)
    assert not dedup.check("chat", "seq", "文本", now=0, commit=False)[0]
    assert not dedup.check("chat", "seq", "文本", now=1)[0]
    assert dedup.check("chat", "seq", "文本", now=5)[0]
    assert not dedup.check("chat", "seq", "文本", now=16)[0]


def test_retained_snapshot_does_not_expire_into_duplicate_event():
    dedup = OcrDedup(window_sec=10)
    seq = dedup.snapshot_sequences("chat", ["文本"])[0]
    assert not dedup.check("chat", seq, "文本", now=0)[0]
    assert dedup.snapshot_sequences("chat", ["文本"])[0] == seq
    assert dedup.check("chat", seq, "文本", now=100)[0]


def test_snapshot_and_record_capacity_is_bounded():
    dedup = OcrDedup(max_keep=3)
    for i in range(10):
        seq = dedup.snapshot_sequences(str(i), [str(i)])[0]
        dedup.check(str(i), seq, str(i), now=i)
    assert sum(len(items) for items in dedup._snapshots.values()) <= 3
    assert len(dedup._seen_seq) <= 3
    assert len(dedup._seen_fp) <= 3


def test_chats_have_separate_snapshot_identity():
    dedup = OcrDedup()
    first = dedup.snapshot_sequences("甲群", ["收到", "收到"])
    second = dedup.snapshot_sequences("乙群", ["收到", "收到"])
    assert not set(first) & set(second)
    assert dedup.snapshot_sequences("甲群", ["收到", "收到"]) == first
