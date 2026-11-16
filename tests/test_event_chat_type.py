"""验证事件记录的会话类型字段，并检查采集函数中相关调用的源码。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from txrui import state as _st


class TestPushEventCarriesChatType:
    def test_push_event_records_chat_type(self):
        _st.push_event("摸鱼集团", "张三", "hi", chat_type="group")
        ev = _st.get_events(1)[0]
        assert ev["chat_type"] == "group"
        assert ev["chat"] == "摸鱼集团"
        assert ev["sender"] == "张三"

    def test_push_event_private(self):
        _st.push_event("张三", "张三", "hi", chat_type="private")
        assert _st.get_events(1)[0]["chat_type"] == "private"

    def test_missing_chat_type_stays_empty_not_guessed(self):
        """缺失会话类型时记录空字符串。"""
        _st.push_event("张三", "张三", "hi")
        assert _st.get_events(1)[0]["chat_type"] == ""

    def test_chat_type_is_normalized_lowercase(self):
        _st.push_event("群", "群", "hi", chat_type=" GROUP ")
        assert _st.get_events(1)[0]["chat_type"] == "group"

    def test_legacy_call_signature_still_works(self):
        """仅传入会话、发送者和文本时，类型字段默认为空。"""
        _st.push_event("张三", "张三", "hi")
        ev = _st.get_events(1)[0]
        assert ev["text"] == "hi"
        assert ev["chat_type"] == ""


class TestCollectorPassesChatType:
    """检查采集函数源码包含会话类型检测及关键字传参。"""

    def test_collector_call_site_includes_chat_type(self):
        import inspect
        from txrui import collector

        src = inspect.getsource(collector.poll_once)
        assert "chat_type=chat_type" in src, "poll_once 未把 chat_type 传给 push_event"

    def test_collector_detects_chat_type_before_payload(self):
        """检查采集函数包含类型检测调用和 chat_type 关键字参数。"""
        import inspect
        from txrui import collector

        src = inspect.getsource(collector.poll_once)
        # 这里只检查源码片段，不验证运行时调用顺序或参数值。
        assert "detect_chat_type(" in src
        assert "chat_type=chat_type" in src


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-q"])
