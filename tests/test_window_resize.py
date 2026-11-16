"""用模拟 Windows 接口验证窗口尺寸调整、窗口还原和失败处理。"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="需要 Windows")


@pytest.fixture
def capture():
    from txrui import capture
    return capture


@pytest.mark.parametrize("minimized,maximized", [(False, False), (True, False), (False, True)])
def test_resize_default_physical_size(capture, minimized, maximized):
    api = Mock()
    api.IsIconic.return_value = minimized
    api.IsZoomed.return_value = maximized
    api.SetWindowPos.return_value = True
    with patch.object(capture, "u32", api), \
            patch.object(capture, "_with_per_monitor_dpi", side_effect=lambda fn: fn()), \
            patch.object(capture.time, "sleep"), \
            patch.object(capture, "window_rect", side_effect=[(50, 60, 1118, 809), (50, 60, 1500, 1000)]):
        assert capture.resize_wechat_window(123)
    api.SetWindowPos.assert_called_once_with(123, None, 0, 0, 1500, 1000, 0x16)
    assert api.ShowWindow.called == (minimized or maximized)


def test_already_target_size(capture):
    api = Mock()
    api.IsIconic.return_value = api.IsZoomed.return_value = False
    with patch.object(capture, "u32", api), \
            patch.object(capture, "_with_per_monitor_dpi", side_effect=lambda fn: fn()), \
            patch.object(capture, "window_rect", return_value=(0, 0, 1500, 1000)):
        assert capture.resize_wechat_window(123)
    api.SetWindowPos.assert_not_called()


def test_resize_failure(capture):
    api = Mock()
    api.IsIconic.return_value = api.IsZoomed.return_value = False
    api.SetWindowPos.return_value = False
    with patch.object(capture, "u32", api), \
            patch.object(capture, "_with_per_monitor_dpi", side_effect=lambda fn: fn()), \
            patch.object(capture, "window_rect", return_value=(0, 0, 1118, 809)):
        assert not capture.resize_wechat_window(123)


def test_invalid_window(capture):
    assert not capture.resize_wechat_window(None)
