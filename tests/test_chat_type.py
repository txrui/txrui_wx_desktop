"""验证标题解析、私信与群聊判定、类型标签及消息字段的默认值。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from txrui.regions import (CHAT_TYPE_GROUP, CHAT_TYPE_PRIVATE,
                           chat_type_label, detect_chat_type, parse_title)


class TestParseTitle:
    def test_private_chat(self):
        assert parse_title("张三") == ("张三", False, None)

    def test_group_chat_ascii_parentheses(self):
        assert parse_title("摸鱼集团(5)") == ("摸鱼集团", True, 5)

    def test_group_chat_fullwidth_parentheses(self):
        assert parse_title("摸鱼集团（5）") == ("摸鱼集团", True, 5)

    def test_group_chat_with_spaces(self):
        assert parse_title("摸鱼集团 ( 5 )") == ("摸鱼集团", True, 5)

    def test_group_name_with_parentheses(self):
        assert parse_title("产品(研发)(8)") == ("产品(研发)", True, 8)

    def test_private_name_ending_with_digits_is_not_group(self):
        assert parse_title("用户123") == ("用户123", False, None)

    def test_empty_title(self):
        assert parse_title("") == ("", False, None)


class TestDetectChatType:
    def test_private_by_default(self):
        d = detect_chat_type("张三")
        assert d["chat_type"] == CHAT_TYPE_PRIVATE
        assert d["is_group"] is False
        assert d["member_count"] is None

    def test_group_by_member_suffix(self):
        d = detect_chat_type("摸鱼集团(5)")
        assert d["chat_type"] == CHAT_TYPE_GROUP
        assert d["is_group"] is True
        assert d["member_count"] == 5

    def test_group_fullwidth_suffix(self):
        d = detect_chat_type("摸鱼集团（12）")
        assert d["chat_type"] == CHAT_TYPE_GROUP
        assert d["member_count"] == 12

    def test_explicit_is_group_true(self):
        d = detect_chat_type("任何名字", is_group=True, member_count=7)
        assert d["chat_type"] == CHAT_TYPE_GROUP
        assert d["member_count"] == 7

    def test_explicit_is_group_false(self):
        d = detect_chat_type("任何名字", is_group=False)
        assert d["chat_type"] == CHAT_TYPE_PRIVATE
        assert d["member_count"] is None

    def test_name_with_non_numeric_parens_is_private(self):
        # 「产品(研发)」不是人数后缀 → 私信
        d = detect_chat_type("产品(研发)")
        assert d["chat_type"] == CHAT_TYPE_PRIVATE
        assert d["is_group"] is False

    def test_empty_title_is_private(self):
        d = detect_chat_type("")
        assert d["chat_type"] == CHAT_TYPE_PRIVATE

    def test_reason_is_not_empty(self):
        assert detect_chat_type("摸鱼集团(5)")["reason"]
        assert detect_chat_type("张三")["reason"]

    def test_chat_type_label(self):
        assert chat_type_label(CHAT_TYPE_GROUP) == "群聊"
        assert chat_type_label(CHAT_TYPE_PRIVATE) == "私信"
        assert chat_type_label("") == "未知"
        assert chat_type_label("weird") == "未知"


class TestPayloadChatType:
    """验证事件载荷保留有效会话类型，并对未知类型使用默认值。"""

    def test_payload_carries_chat_type(self):
        from txrui.payload import message_to_payload
        p = message_to_payload("acc", "张三", "张三", "hi", chat_type="private")
        assert p["chat_type"] == "private"
        p2 = message_to_payload("acc", "群", "群", "hi", chat_type="group")
        assert p2["chat_type"] == "group"

    def test_payload_unknown_type_falls_back_to_private(self):
        from txrui.payload import message_to_payload
        p = message_to_payload("acc", "张三", "张三", "hi", chat_type="weird")
        assert p["chat_type"] == "private"
        p2 = message_to_payload("acc", "张三", "张三", "hi", chat_type="")
        assert p2["chat_type"] == "private"
