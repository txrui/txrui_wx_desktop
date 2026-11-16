"""模拟启动准备流程，验证窗口连接、缩放测量顺序和采集状态。"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="需要 Windows")


def test_prepare_applies_backend_without_starting_collection():
    from txrui.runtime import Runtime
    from txrui import state
    runtime = Runtime()
    backend = Mock(_hwnd=123)
    with patch("txrui.backend.TxruiBackend", return_value=backend), \
            patch("txrui.capture._with_per_monitor_dpi", side_effect=lambda fn: fn()), \
            patch("txrui.capture.window_rect", return_value=(100, 200, 1500, 1000)), \
            patch("txrui.capture.monitor_dpi_scale", return_value=125), \
            patch("txrui.scale.active_scale", return_value=125), \
            patch.object(state, "set_field") as set_field, patch.object(state, "log"):
        assert runtime.prepare_wechat()
    backend.connect.assert_called_once()
    assert runtime.backend is backend
    assert runtime.thread is None
    assert runtime.client is None
    set_field.assert_any_call("wechat_window_rect", [100, 200, 1500, 1000])
    set_field.assert_any_call("wechat_active_scale", 125)


def test_missing_wechat_does_not_prevent_panel_start():
    from txrui.runtime import Runtime
    from txrui import state
    runtime = Runtime()
    with patch("txrui.backend.TxruiBackend") as factory, \
            patch.object(state, "set_field"), patch.object(state, "log"):
        factory.return_value.connect.side_effect = RuntimeError("未找到微信窗口")
        assert not runtime.prepare_wechat()
    assert runtime.backend is None


def test_connect_measures_dpi_after_resize():
    from txrui.backend import TxruiBackend
    from PIL import Image
    events = []
    with patch("txrui.backend._cap.find_wechat_window", return_value=123), \
            patch("txrui.backend._cap.ensure_visible"), \
            patch("txrui.backend._cap.resize_wechat_window", side_effect=lambda hwnd, width, height: events.append("resize") or True), \
            patch("txrui.backend._cap._with_per_monitor_dpi", return_value=(0, 0, 1500, 1000)), \
            patch("txrui.backend._cap.monitor_dpi_scale", side_effect=lambda hwnd: events.append("dpi") or 125), \
            patch("txrui.backend._scale.set_active_scale", return_value=125) as apply, \
            patch("txrui.backend._cap.capture_window", return_value=Image.new("RGB", (100, 100))), \
            patch.object(TxruiBackend, "_apply_regions"):
        assert TxruiBackend().connect()
    assert events == ["resize", "dpi"]
    apply.assert_called_once_with(125)
