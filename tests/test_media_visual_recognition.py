"""用合成截图验证文字、表情、图片和视频的区分，以及媒体消息构建。"""
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui import media, payload
from txrui.media_vision import component_boxes


def scene():
    image = Image.new("RGB", (385, 680), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((14, 24, 93, 60), radius=6, fill=(237, 237, 237))
    draw.text((24, 35), "TEXT", fill=(20, 20, 20))
    draw.rounded_rectangle((14, 80, 57, 117), radius=6, fill=(237, 237, 237))
    draw.ellipse((26, 90, 44, 108), fill=(255, 193, 25))
    draw.arc((27, 91, 43, 106), 0, 180, fill=(220, 125, 10), width=2)
    draw.ellipse((29, 95, 32, 98), fill="white")
    draw.ellipse((37, 95, 40, 98), fill="white")
    draw.line((31, 103, 39, 103), fill=(90, 50, 0), width=1)
    # 两张竖图包含内部文字，仅下方图片带右下角时长标记。
    for top in (138, 405):
        yy, xx = np.indices((245, 112))
        pixels = np.stack(((xx * 2 + yy) % 190 + 15,
                           (yy + xx) % 180 + 15,
                           (yy * 2 + xx) % 180 + 15), axis=2).astype("uint8")
        image.paste(Image.fromarray(pixels), (14, top))
    draw = ImageDraw.Draw(image)
    draw.text((20, 145), "SCREENSHOT", fill="white")
    draw.text((20, 412), "MENU TEXT", fill="white")
    draw.text((90, 630), "0:52", fill="white")
    items = [dict(x=24, y=35, w=56, h=18, text="这是文字"),
             dict(x=20, y=145, w=85, h=14, text="截图上的文字"),
             dict(x=20, y=412, w=85, h=14, text="仪表盘 菜单"),
             dict(x=90, y=630, w=32, h=14, text="0:52")]
    return image, items


@pytest.mark.parametrize("scale", [100, 125, 175])
def test_example_layout_detects_emoji_image_and_video(scale):
    image, items = scene()
    bubbles = media.detect_media_bubbles(image, items, scale)
    assert [b["kind"] for b in bubbles] == ["emoji", "image", "video"]
    assert bubbles[-1]["duration"] == "0:52"
    assert all(b["reason"] and 0 < b["confidence"] <= 1 for b in bubbles)


def test_unicode_emoji_from_ocr_does_not_hide_color_evidence():
    image, items = scene()
    items.append(dict(x=26, y=90, w=19, h=19, text="🙄"))
    assert media.detect_media_bubbles(image, items, 175)[0]["kind"] == "emoji"


def test_grayscale_picture_with_text_is_not_discarded():
    image, items = scene()
    bubbles = media.detect_media_bubbles(image.convert("L"), items, 175)
    assert [b["kind"] for b in bubbles] == ["image", "video"]


def test_time_inside_picture_is_not_video_duration():
    image, items = scene()
    items[-1].update(y=430, text="12:30")
    bubbles = media.detect_media_bubbles(image, items, 175)
    assert bubbles[-1]["kind"] == "image"


def test_unknown_video_without_duration_remains_image():
    image, items = scene()
    bubbles = media.detect_media_bubbles(image, items[:-1], 175)
    assert bubbles[-1]["kind"] == "image"


def test_light_green_bubble_is_not_an_emoji():
    image = Image.new("RGB", (500, 150), (250, 250, 250))
    ImageDraw.Draw(image).rounded_rectangle((300, 40, 355, 80), radius=5, fill=(158, 237, 151))
    assert media.detect_media_bubbles(image, [], 175) == []


def test_components_do_not_join_avatar_to_picture():
    mask = np.zeros((200, 200), dtype=bool)
    mask[10:60, 5:55] = True
    mask[10:180, 80:190] = True
    assert component_boxes(mask) == [(5, 10, 55, 60), (80, 10, 190, 180)]


def test_components_merge_bridge_correctly():
    mask = np.zeros((20, 30), dtype=bool)
    mask[1:10, 1:5] = True
    mask[1:10, 20:25] = True
    mask[9:15, 1:25] = True
    assert component_boxes(mask) == [(1, 1, 25, 15)]


def test_uploaded_emoji_keeps_image_id_in_payload():
    segment = payload.build_media_segment(dict(kind="emoji"), media_id="emoji_1", mime="image/png")
    event = payload.message_to_payload("account", "chat", "sender", "", msg_type="emoji", media_segments=[segment])
    assert event["content"][0]["media_id"] == "emoji_1"
    assert event["content"][0]["type"] == "text"
    assert event["content"][0]["extra"]["emoji"] is True
    other = payload.build_media_segment(dict(kind="emoji"), media_id="emoji_2", mime="image/png")
    event2 = payload.message_to_payload("account", "chat", "sender", "", msg_type="emoji", media_segments=[other])
    assert event["fingerprint"] != event2["fingerprint"]


@pytest.mark.skipif(sys.platform != "win32", reason="backend 依赖 Windows")
def test_picture_ocr_is_not_reported_as_chat_messages():
    from txrui.backend import TxruiBackend
    image, items = scene()
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    with patch.object(backend, "read_title", return_value="测试会话"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items), \
            patch("txrui.scale.active_scale", return_value=175):
        messages = backend.get_messages(None, detect_media=True)
    assert [(m["type"], m["content"]) for m in messages] == [
        ("text", "这是文字"), ("emoji", ""), ("image", ""), ("video", "")]


@pytest.mark.skipif(sys.platform != "win32", reason="backend 依赖 Windows")
@pytest.mark.parametrize("nickname_height", [14, 20])
def test_group_picture_uses_nickname_and_does_not_emit_it_as_text(nickname_height):
    from txrui.backend import TxruiBackend
    image = Image.new("RGB", (600, 400), (250, 250, 250))
    items = [dict(x=40, y=30, w=80, h=nickname_height, text="田瑞工作室"),
             dict(x=40, y=230, w=80, h=14, text="田瑞工作室"),
             dict(x=52, y=252, w=40, h=20, text="哈哈")]
    bubbles = [dict(x=40, y=55, w=120, h=150, kind="image")]
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    with patch("txrui.scale.k", return_value=125 / 175), \
            patch.object(backend, "read_title", return_value="田瑞工作室、田瑞工作室、田小瑞(3)"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items), \
            patch("txrui.media.detect_media_bubbles", return_value=bubbles), \
            patch("txrui.message_layout.text_is_self", return_value=False):
        messages = backend.get_messages(None, detect_media=True)
    assert [(m["type"], m["sender"], m["content"]) for m in messages] == [
        ("image", "田瑞工作室", ""), ("text", "田瑞工作室", "哈哈")]

