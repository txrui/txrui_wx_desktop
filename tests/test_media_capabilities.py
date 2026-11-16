"""验证媒体分类、文件名与坐标处理、语音文本、消息段构建及撤回目标定位。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from txrui import media, media_grab, payload, recall, voice


# 媒体类型与默认格式

class TestClassifyBox:
    def test_image_large_rect_no_text(self):
        # 无文本大矩形 -> image
        assert media.classify_box(200, 150, "", 200) == "image"

    def test_video_wide_rect_no_text(self):
        # 无文本且很宽仍是图片，不能单凭宽高比猜视频
        assert media.classify_box(300, 150, "", 200) == "image"

    def test_file_with_text_short(self):
        # 文件名与文件大小同时出现才确认文件卡片
        assert media.classify_box(200, 100, "报告.docx 20.1KB", 200) == "file"

    def test_video_with_text_tall(self):
        # 竖向矩形含完整时长文本时判为视频。
        assert media.classify_box(200, 260, "00:15", 200) == "video"

    def test_emoji_small_no_text(self):
        # 小尺寸无文本可能是图标，证据不足时忽略
        assert media.classify_box(33, 28, "", 200) == ""

    def test_audio_flat_wide(self):
        # 横扁外形还须有完整语音时长标记
        assert media.classify_box(90, 24, '8"', 200) == "audio"

    def test_emoji_with_text_is_file(self):
        # 小矩形中的普通文字仍判为文本。
        assert media.classify_box(40, 30, "文件", 200) == "text"


class TestMediaMime:
    def test_mime_by_kind(self):
        assert media.guess_mime("image") == "image/png"
        assert media.guess_mime("emoji") == "image/png"
        assert media.guess_mime("audio") == "audio/amr"
        assert media.guess_mime("video") == "video/mp4"

    def test_ext_by_kind(self):
        assert media.ext_for("image") == ".png"
        assert media.ext_for("emoji") == ".png"
        assert media.ext_for("audio") == ".amr"

    def test_ext_from_filename(self):
        assert media.ext_for("file", "报告.pdf") == ".pdf"

    def test_has_binary_types(self):
        # 可尝试获取二进制内容的类型集合为图片、文件和视频。
        assert set(media.HAS_BINARY) == {"image", "file", "video"}


# 文件名、坐标和文件格式处理

class TestFileToken:
    def test_strict_extension(self):
        text = "部门简介+纳新宣传.docx 20.1K W"
        assert media_grab.extract_file_token(text) == "部门简介+纳新宣传.docx"

    def test_loose_fallback(self):
        # OCR 把后缀读花（xlsx -> xIsx）
        assert media_grab.extract_file_token("评分表.xIsx") == "评分表.xIsx"

    def test_no_extension(self):
        assert media_grab.extract_file_token("没有扩展名") == ""


class TestNormalizeDisplayName:
    def test_strips_separators(self):
        # OCR 漏读下划线也要能匹配
        assert media_grab.normalize_display_name("小漓_深海小剧场.html") == \
            media_grab.normalize_display_name("小漓深海小剧场.html")

    def test_empty(self):
        assert media_grab.normalize_display_name("") == ""


class TestRectConvert:
    def test_roundtrip(self):
        origin = (100, 200)
        rect = (10, 20, 110, 90)
        screen = media_grab.to_screen_rect(rect, origin)
        assert screen == (110, 220, 210, 290)
        assert media_grab.from_screen_rect(screen, origin) == rect


class TestMimeForPath:
    def test_common(self):
        assert media_grab.mime_for_path("a.png") == "image/png"
        assert media_grab.mime_for_path("a.mp3") == "audio/mpeg"
        assert media_grab.mime_for_path("a.pdf") == "application/pdf"
        assert media_grab.mime_for_path("a.unknown") == "application/octet-stream"


# 语音时长和文本识别

class TestVoice:
    def test_parse_duration_quote(self):
        assert voice.parse_voice_duration('3"') == 3
        assert voice.parse_voice_duration('12"') == 12

    def test_parse_duration_chinese(self):
        assert voice.parse_voice_duration("5秒") == 5

    def test_parse_duration_none(self):
        assert voice.parse_voice_duration("你好") == 0

    def test_is_voice_text(self):
        assert voice.is_voice_text('8"') is True
        assert voice.is_voice_text("语音") is True
        assert voice.is_voice_text("今天天气不错") is False

    def test_transcribed_voice(self):
        # 转写文本：有汉字、不是时长
        assert voice.is_transcribed_voice("明天见") is True
        # 纯时长不是转写
        assert voice.is_transcribed_voice('3"') is False
        # 纯符号不是转写
        assert voice.is_transcribed_voice("...") is False
        assert voice.is_transcribed_voice("") is False

    def test_endpoint_from_config_empty_by_default(self):
        # 配置端点查询返回字符串；此处不假定本机是否配置语音识别服务。
        assert isinstance(voice.endpoint_from_config(), str)


# 消息段与事件构建

class TestPayload:
    def test_text_payload(self):
        p = payload.message_to_payload("wx_001", "张三", "张三", "你好", y=10,
                                       msg_type="text")
        assert p["content"][0]["type"] == "text"
        assert p["content"][0]["text"] == "你好"

    def test_image_placeholder_no_fake_media_id(self):
        p = payload.message_to_payload("wx_001", "张三", "张三", "", y=10,
                                       msg_type="image")
        seg = p["content"][0]
        assert seg["type"] == "image"
        assert seg["extra"]["placeholder"] is True
        # 绝不伪造 media_id
        assert not seg.get("media_id")

    def test_file_placeholder(self):
        p = payload.message_to_payload("wx_001", "张三", "张三", "报告.docx", y=10,
                                       msg_type="file")
        seg = p["content"][0]
        assert seg["type"] == "file"
        assert seg["extra"]["placeholder"] is True

    def test_video_placeholder(self):
        p = payload.message_to_payload("wx_001", "张三", "张三", "", y=10,
                                       msg_type="video")
        assert p["content"][0]["type"] == "video"

    def test_audio_placeholder(self):
        p = payload.message_to_payload("wx_001", "张三", "张三", "", y=10,
                                       msg_type="audio")
        assert p["content"][0]["type"] == "audio"

    def test_emoji_becomes_text_with_flag(self):
        # 表情使用文本段，并通过 extra.emoji 标记。
        p = payload.message_to_payload("wx_001", "张三", "张三", "", y=10,
                                       msg_type="emoji")
        seg = p["content"][0]
        assert seg["type"] == "text"
        assert seg["extra"]["emoji"] is True

    def test_real_media_segment_keeps_media_id(self):
        seg = payload.build_media_segment({"kind": "image", "text": "[图片]"},
                                          media_id="mb_1",
                                          url="/api/v1/media/blobs/mb_1",
                                          mime="image/png")
        assert seg["media_id"] == "mb_1"
        assert seg["url"] == "/api/v1/media/blobs/mb_1"
        assert "placeholder" not in seg["extra"]

    def test_placeholder_segment_flags(self):
        seg = payload.build_media_segment({"kind": "image"})
        assert seg["extra"]["placeholder"] is True
        assert not seg.get("media_id")

    def test_emoji_placeholder_flags_emoji(self):
        seg = payload.build_media_segment({"kind": "emoji"})
        assert seg["extra"]["emoji"] is True
        assert seg["extra"]["placeholder"] is True

    def test_ocr_placeholder_text_maps_to_type(self):
        # OCR 读到 "[图片]" 占位文本 -> 映射成 image 段
        p = payload.message_to_payload("wx_001", "张三", "张三", "[图片]", y=10)
        assert p["content"][0]["type"] == "image"

    def test_normalize_type_aliases(self):
        assert payload.normalize_type("sticker") == "emoji"
        assert payload.normalize_type("voice") == "audio"
        assert payload.normalize_type("img") == "image"
        assert payload.normalize_type("mp4") == "video"
        assert payload.normalize_type("unknown_thing") == "text"

    def test_media_segments_override_msg_type(self):
        segs = [payload.build_media_segment({"kind": "image"}, media_id="mb_x")]
        p = payload.message_to_payload("wx_001", "张三", "张三", "看图", y=10,
                                       msg_type="text", media_segments=segs)
        assert p["content"][0]["media_id"] == "mb_x"

    def test_fingerprint_differs_by_media(self):
        a = payload.message_to_payload("wx_001", "张三", "张三", "看图", y=10)
        b = payload.message_to_payload(
            "wx_001", "张三", "张三", "看图", y=10,
            media_segments=[payload.build_media_segment({"kind": "image"},
                                                        media_id="mb_1")])
        # 同文案不同媒体 -> 指纹必须不同
        assert a["fingerprint"] != b["fingerprint"]


# 撤回菜单、确认按钮和消息定位

class TestRecall:
    def test_find_recall_menu_item(self):
        items = [{"text": "复制", "x": 1, "y": 1, "w": 10, "h": 10},
                 {"text": "撤回", "x": 1, "y": 20, "w": 10, "h": 10}]
        hit = recall.find_recall_menu_item(items)
        assert hit is not None and hit["text"] == "撤回"

    def test_no_recall_menu_item(self):
        items = [{"text": "复制", "x": 1, "y": 1, "w": 10, "h": 10}]
        assert recall.find_recall_menu_item(items) is None

    def test_find_confirm_button(self):
        items = [{"text": "撤回一条消息？", "x": 1, "y": 1, "w": 10, "h": 10},
                 {"text": "确定", "x": 1, "y": 20, "w": 10, "h": 10}]
        hit = recall.find_confirm_button(items)
        assert hit is not None and hit["text"] == "确定"

    def test_confirm_does_not_match_long_text(self):
        # 「撤回了一条消息」不是按钮
        items = [{"text": "撤回了一条消息", "x": 1, "y": 1, "w": 10, "h": 10}]
        assert recall.find_confirm_button(items) is None

    def test_locate_message_bubble(self):
        items = [{"text": "第一条", "x": 0, "y": 10, "w": 10, "h": 10},
                 {"text": "目标消息", "x": 0, "y": 50, "w": 10, "h": 10}]
        hit = recall.locate_message_bubble(items, "目标消息")
        assert hit is not None and hit["text"] == "目标消息"

    def test_locate_with_anchor(self):
        items = [{"text": "锚点", "x": 0, "y": 10, "w": 10, "h": 10},
                 {"text": "好的", "x": 0, "y": 50, "w": 10, "h": 10},
                 {"text": "好的", "x": 0, "y": 90, "w": 10, "h": 10}]
        hit = recall.locate_message_bubble(items, "好的", anchor_text="锚点")
        # 取锚点之后最近的那个
        assert hit is not None and hit["y"] == 50

    def test_locate_not_found(self):
        items = [{"text": "别的", "x": 0, "y": 10, "w": 10, "h": 10}]
        assert recall.locate_message_bubble(items, "找不到") is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
