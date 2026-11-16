"""用合成截图验证消息发送方判定、输入区边界及自身消息过滤。"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui.message_layout import text_is_self
from txrui.regions import detect_input_top_y, regions_for_window


def test_green_continuation_left_of_midline_is_self():
    image = Image.new("RGB", (740, 540), (250, 250, 250))
    ImageDraw.Draw(image).rectangle((160, 100, 680, 160), fill=(158, 237, 151))
    assert text_is_self(image, {"x": 173, "y": 110, "w": 186, "h": 30})


def test_gray_incoming_is_other():
    image = Image.new("RGB", (740, 540), (250, 250, 250))
    ImageDraw.Draw(image).rectangle((100, 100, 380, 150), fill=(237, 237, 237))
    assert not text_is_self(image, {"x": 114, "y": 110, "w": 252, "h": 23})


def test_small_green_icon_is_not_self():
    image = Image.new("RGB", (740, 540), (237, 237, 237))
    ImageDraw.Draw(image).rectangle((115, 110, 120, 115), fill=(158, 237, 151))
    assert not text_is_self(image, {"x": 114, "y": 110, "w": 252, "h": 23})


def test_input_border_wins_over_bottom_send_button():
    image = Image.new("RGB", (1100, 800), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.line((390, 620, 1080, 620), fill=(225, 225, 225), width=1)
    draw.rectangle((990, 740, 1060, 770), fill=(100, 100, 100))
    assert detect_input_top_y(image, 380, 1080) == 620


def test_button_alone_is_not_input_boundary():
    image = Image.new("RGB", (1100, 800), (250, 250, 250))
    ImageDraw.Draw(image).rectangle((990, 740, 1060, 770), fill=(100, 100, 100))
    assert detect_input_top_y(image, 380, 1080) is None


def test_input_boundary_does_not_cut_last_30_pixels():
    message = regions_for_window(1100, 800, 125, boundary_px=380,
                                 header_y=90, input_top_y=620)[1]
    assert message[3] * 800 == pytest.approx(618)


def test_group_sender_name_is_separate_from_message_body():
    from txrui.backend import TxruiBackend

    image = Image.new("RGB", (1000, 800), (250, 250, 250))
    items = [
        {"text": "张三", "x": 45, "y": 100, "w": 32, "h": 16},
        {"text": "大家好，今天开会", "x": 72, "y": 124, "w": 150, "h": 24},
    ]
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    with patch.object(backend, "read_title", return_value="测试群(3)"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items):
        messages = backend.get_messages(None)
    assert len(messages) == 1
    assert messages[0]["sender"] == "张三"
    assert messages[0]["content"] == "大家好，今天开会"


def test_group_standalone_short_message_is_not_dropped():
    from txrui.backend import TxruiBackend

    image = Image.new("RGB", (1000, 800), (250, 250, 250))
    items = [{"text": "收到", "x": 72, "y": 124, "w": 40, "h": 24}]
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    with patch.object(backend, "read_title", return_value="测试群(3)"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items):
        messages = backend.get_messages(None)
    assert [m["content"] for m in messages] == ["收到"]


def group_messages(items):
    from txrui.backend import TxruiBackend

    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    image = Image.new("RGB", (1000, 800), (250, 250, 250))
    with patch.object(backend, "read_title", return_value="测试群(3)"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items):
        return backend.get_messages(None)


def test_group_paired_body_is_not_consumed_again_as_sender():
    messages = group_messages([
        {"text": "张三", "x": 45, "y": 100, "w": 32, "h": 16},
        {"text": "收到", "x": 72, "y": 124, "w": 40, "h": 24},
        {"text": "张三", "x": 72, "y": 175, "w": 32, "h": 16},
        {"text": "发个图片", "x": 72, "y": 199, "w": 96, "h": 24},
    ])
    assert [(m["sender"], m["content"]) for m in messages] == [
        ("张三", "收到"), ("张三", "发个图片"),
    ]


def test_adjacent_same_size_short_bodies_are_not_sender_labels():
    messages = group_messages([
        {"text": "发个表情", "x": 72, "y": 100, "w": 96, "h": 24},
        {"text": "/发个表情", "x": 72, "y": 145, "w": 104, "h": 24},
    ])
    assert [m["content"] for m in messages] == ["发个表情", "/发个表情"]


def test_group_short_body_before_smaller_sender_label_is_preserved():
    messages = group_messages([
        {"text": "收到", "x": 72, "y": 100, "w": 40, "h": 24},
        {"text": "张三", "x": 72, "y": 145, "w": 32, "h": 16},
        {"text": "好的", "x": 72, "y": 169, "w": 48, "h": 24},
    ])
    assert [m["content"] for m in messages] == ["收到", "好的"]
    assert messages[-1]["sender"] == "张三"


@pytest.mark.skipif(sys.platform != "win32", reason="backend 依赖 Windows 截图模块")
def test_latest_message_excludes_self_continuations():
    from txrui.backend import TxruiBackend
    image = Image.new("RGB", (740, 540), (250, 250, 250))
    ImageDraw.Draw(image).rectangle((160, 100, 680, 350), fill=(158, 237, 151))
    items = [
        {"text": "自己的长消息首行", "x": 190, "y": 110, "w": 440, "h": 25},
        {"text": "自己的短续行", "x": 173, "y": 140, "w": 186, "h": 30},
        {"text": "自己的另一条续行", "x": 190, "y": 300, "w": 245, "h": 25},
        {"text": "我正在测试机器人回复信息问题", "x": 114, "y": 466, "w": 252, "h": 23},
    ]
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    with patch.object(backend, "read_title", return_value="测试会话"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items):
        messages = backend.get_messages(None)
    assert [m["content"] for m in messages] == ["我正在测试机器人回复信息问题"]
