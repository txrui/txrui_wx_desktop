"""验证正向桌面文字识别、英文群标题及上报人数的回归场景。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

from txrui import collector, ocr, state
from txrui.backend import TxruiBackend
from txrui.dedup import OcrDedup
from txrui.regions import parse_title


def test_desktop_ocr_explicitly_disables_angle_classifier_on_every_call():
    # 模拟方向分类把英文标题翻转后产生的乱码，确保不走该分支。
    def recognize(image, *, use_cls):
        text = "(t) 2o!pnns !nuxl" if use_cls else "Txrui Studio2 (4)"
        return SimpleNamespace(txts=[text], scores=[0.99],
                               boxes=[[[0, 0], [180, 0], [180, 24], [0, 24]]])

    engine = Mock(side_effect=recognize)
    with patch.object(ocr, "get_engine", return_value=engine):
        for _ in range(2):
            result = ocr.ocr_image(Image.new("RGB", (927, 52), "white"))
            assert parse_title(result[0]["text"]) == ("Txrui Studio2", True, 4)
    assert engine.call_count == 2
    assert all(call.kwargs == {"use_cls": False} for call in engine.call_args_list)


@pytest.mark.parametrize("parts, expected", [
    (["Txrui Studio2", "(4)"], "Txrui Studio2(4)"),
    (["群", "（", "4", "）", "..."], "群（4）"),
])
def test_title_is_upscaled_and_preserves_single_character_parts(parts, expected):
    backend = TxruiBackend()
    backend._title_region = (0, 0, 1, 1)
    items = [{"text": text, "x": idx * 50} for idx, text in enumerate(parts)]
    with patch.object(backend, "_shot", return_value=Image.new("RGB", (927, 52), "white")), \
            patch("txrui.backend._ocr.ocr_image", return_value=items) as recognize:
        assert backend.read_title() == expected
    assert recognize.call_args.kwargs == {"upscale": 2.0}
    assert parse_title(expected)[1:] == (True, 4)


@pytest.mark.parametrize("title", ["Txrui Studio2 (4)", "Txrui Studio2（4）"])
def test_english_group_title_keeps_type_and_member_count_in_events(title):
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    image = Image.new("RGB", (1000, 800), "white")
    items = [{"text": "电机", "x": 72, "y": 100, "w": 48, "h": 24}]
    client = Mock(connector_id="test_connector")
    with patch.object(backend, "read_title", return_value=title), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items), \
            patch.object(backend, "iter_unread_sessions", return_value=[(1, 2)]), \
            patch.object(backend, "mark_session_read"), \
            patch.object(state, "push_event") as push:
        assert asyncio.run(collector.poll_once(backend, client, "account", OcrDedup())) == 1
    payload = client.queue_event.call_args.args[0]
    assert payload["chat_type"] == "group"
    assert payload["extra"]["group_member_count"] == 4
    assert backend._current_title == "Txrui Studio2"
    assert push.call_args.args[0] == "Txrui Studio2"
    assert push.call_args.kwargs["chat_type"] == "group"


@pytest.mark.parametrize("title", ["Txrui Studio2 (4)", "标题识别失败"])
def test_group_rename_notice_is_not_reported_as_a_message(title):
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    items = [
        {"text": '你修改群名为“Txrui Studio2"', "x": 300, "y": 100, "w": 350, "h": 24},
        {"text": "我想修改群名为新名字", "x": 72, "y": 200, "w": 240, "h": 24},
    ]
    with patch.object(backend, "read_title", return_value=title), \
            patch.object(backend, "_shot", return_value=Image.new("RGB", (1000, 800), "white")), \
            patch("txrui.backend._ocr.ocr_image", return_value=items):
        messages = backend.get_messages(None)
    assert [m["content"] for m in messages] == ["我想修改群名为新名字"]
