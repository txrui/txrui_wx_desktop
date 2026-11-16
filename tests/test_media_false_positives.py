"""用合成截图验证文字、头像和相邻文本不会误归为媒体消息。"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui import media
from txrui.message_layout import media_contains_text


@pytest.mark.parametrize("text", ["文件", "ah", "到后", "发个表情", "发个语音", "视频", "报告.docx"])
@pytest.mark.parametrize("size", [(40, 30), (100, 24), (200, 100), (200, 260)])
def test_ordinary_text_is_not_media(text, size):
    assert media.classify_box(*size, text, 200) == "text"


def test_shape_alone_does_not_prove_voice_or_video():
    assert media.classify_box(90, 24, "", 200) == ""
    assert media.classify_box(300, 150, "", 200) == "image"


@pytest.mark.parametrize("scale", [100, 125, 175])
def test_text_pixels_do_not_become_files_or_voice(scale):
    image = Image.new("RGB", (700, 400), (237, 237, 237))
    draw = ImageDraw.Draw(image)
    items = []
    for y, width, text in [(40, 40, "ah"), (120, 130, "发个表情"), (210, 80, "文件")]:
        # 用实心深色矩形模拟高填充率字形，并提供对应的文字识别框。
        draw.rectangle((100, y, 100 + width - 1, y + 23), fill=(30, 30, 30))
        items.append(dict(x=100, y=y, w=width, h=24, text=text))
    assert media.detect_media_bubbles(image, items, scale) == []


def test_avatar_is_not_an_image_message():
    image = Image.new("RGB", (700, 400), (237, 237, 237))
    ImageDraw.Draw(image).rectangle((5, 30, 74, 99), fill=(30, 80, 120))
    assert media.detect_media_bubbles(image, [], 175) == []


def test_large_incoming_image_is_still_detected():
    image = Image.new("RGB", (700, 400), (237, 237, 237))
    ImageDraw.Draw(image).rectangle((100, 30, 299, 179), fill=(30, 80, 120))
    bubbles = media.detect_media_bubbles(image, [], 175)
    assert len(bubbles) == 1
    assert bubbles[0]["kind"] == "image"


@pytest.mark.parametrize("text,size,kind", [('8"', (100, 30), "audio"),
                                          ("报告.docx 20KB", (240, 100), "file"),
                                          ("00:15", (240, 180), "video")])
def test_media_with_explicit_evidence_is_detected(text, size, kind):
    image = Image.new("RGB", (700, 400), (237, 237, 237))
    width, height = size
    ImageDraw.Draw(image).rectangle((100, 40, 100 + width - 1, 40 + height - 1), fill=(100, 100, 100))
    item = dict(x=150, y=40 + height - 25 if kind == "video" else 45,
                w=width - 60, h=20, text=text)
    bubbles = media.detect_media_bubbles(image, [item], 175)
    assert [b["kind"] for b in bubbles] == [kind]


def test_nearby_text_is_not_attached_to_media():
    bubble = dict(x=100, y=100, w=200, h=160)
    assert not media_contains_text(bubble, dict(x=100, y=75, w=100, h=20))
    assert not media_contains_text(bubble, dict(x=350, y=100, w=100, h=20))
    assert media_contains_text(bubble, dict(x=120, y=120, w=100, h=20))


@pytest.mark.skipif(sys.platform != "win32", reason="backend 依赖 Windows")
def test_backend_does_not_attach_adjacent_media_or_report_self_media():
    from txrui.backend import TxruiBackend
    image = Image.new("RGB", (700, 500), (237, 237, 237))
    items = [dict(x=100, y=100, w=100, h=24, text="发个表情")]
    bubbles = [dict(kind="image", x=100, y=130, w=200, h=150, text=""),
               dict(kind="image", x=450, y=320, w=200, h=150, text="")]
    backend = TxruiBackend()
    backend._message_region = (0, 0, 1, 1)
    with patch.object(backend, "read_title", return_value="测试会话"), \
            patch.object(backend, "_shot", return_value=image), \
            patch("txrui.backend._ocr.ocr_image", return_value=items), \
            patch("txrui.media.detect_media_bubbles", return_value=bubbles):
        messages = backend.get_messages(None, detect_media=True)
    assert [(m["content"], m["type"]) for m in messages] == [("发个表情", "text"), ("", "image")]
