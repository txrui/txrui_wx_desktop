"""用合成图、可选本机截图及模拟系统接口验证标题裁剪与窗口截图。"""
import ctypes
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui.regions import detect_divider_x, detect_header_y, regions_for_window


def test_uniform_gray_is_not_divider():
    assert detect_divider_x(Image.new("RGB", (1500, 1000), (237, 237, 237))) is None


def test_real_divider_wins_over_wide_gray_background():
    image = Image.new("RGB", (1500, 1000), (237, 237, 237))
    ImageDraw.Draw(image).line((435, 0, 435, 999), fill=(210, 210, 210))
    assert detect_divider_x(image) == 435


def test_panel_background_edge_is_divider():
    image = Image.new("RGB", (1500, 1000), (237, 237, 237))
    ImageDraw.Draw(image).rectangle((435, 0, 1499, 999), fill=(250, 250, 250))
    assert detect_divider_x(image) == 435


def make_header(scale=175):
    k = scale / 175
    image = Image.new("RGB", (1500, 1000), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    # 以黑色字形块模拟标题，文字本身不能触发边界探测。
    for x in range(465, 600, 20):
        draw.rectangle((x, round(70 * k), x + 10, round(95 * k)), fill="black")
    return image


def test_title_text_is_not_header_boundary():
    assert detect_header_y(make_header(), 445, 1480) is None


def test_real_header_separator_wins_over_text():
    image = make_header()
    ImageDraw.Draw(image).line((435, 120, 1499, 120), fill=(225, 225, 225))
    assert detect_header_y(image, 445, 1480) == 120


def test_header_background_step():
    image = make_header()
    ImageDraw.Draw(image).rectangle((435, 120, 1499, 999), fill=(240, 240, 240))
    assert detect_header_y(image, 445, 1480) == 120


@pytest.mark.parametrize("scale", [100, 125, 150, 175])
def test_title_crop_includes_full_text_at_each_scale(scale):
    image = make_header(scale)
    k = scale / 175
    header = round(120 * k)
    ImageDraw.Draw(image).line((435, header, 1499, header), fill=(225, 225, 225))
    title = regions_for_window(1500, 1000, scale, boundary_px=435, shot=image)[2]
    top, bottom = title[1] * 1000, title[3] * 1000
    assert top < round(70 * k)
    assert bottom > round(95 * k)
    assert bottom < header


def test_tall_calibrated_header_keeps_original_title_band():
    title = regions_for_window(1300, 1610, 175, boundary_px=540, header_y=207)[2]
    assert title[1] * 1610 < 62.1
    assert title[3] * 1610 > 132


def test_no_header_uses_calibrated_region_not_text_row():
    title = regions_for_window(1500, 1000, 175, boundary_px=435, shot=make_header())[2]
    assert title[1] * 1000 == pytest.approx(62.1)
    assert title[3] * 1000 == pytest.approx(132)


@pytest.mark.parametrize("scale", [100, 125, 150, 175])
def test_window_chrome_is_not_chat_header(scale):
    k = scale / 175
    image = Image.new("RGB", (1500, 1000), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    chrome_bottom = round(56 * k)
    header_bottom = round(140 * k)
    draw.rectangle((0, 0, 1499, chrome_bottom - 1), fill=(221, 221, 221))
    draw.line((308, header_bottom, 1499, header_bottom), fill=(225, 225, 225))
    assert detect_header_y(image, 318, 1480, scale) == header_bottom
    _, message, title = regions_for_window(
        1500, 1000, scale, boundary_px=308, shot=image)
    assert title[1] * 1000 < round(95 * k)
    assert title[3] * 1000 == pytest.approx(header_bottom - 2)
    assert message[1] * 1000 == pytest.approx(header_bottom + 4)
    assert message[1] > title[3]


def test_saved_window_header_regression():
    """存在本机保存的截图时检查标题裁剪；缺失时跳过。"""
    path = Path(__file__).resolve().parents[2] / "txrui_debug_window.png"
    if not path.exists():
        pytest.skip("本机故障截图不存在")
    with Image.open(path) as image:
        w, h = image.size
        divider = detect_divider_x(image)
        header = detect_header_y(image, divider + 10, w - 20, 100)
        assert header is not None
        assert 65 <= header <= 95
        _, message, title = regions_for_window(w, h, 100, shot=image)
        assert title[1] * h < 55 < title[3] * h
        assert title[3] * h - title[1] * h > 20
        assert message[1] * h > header


@pytest.mark.skipif(sys.platform != "win32", reason="需要 Windows 截图模块")
class TestCapture:
    def test_capture_uses_physical_dpi_context(self):
        from txrui import capture
        api = Mock()
        api.IsIconic.return_value = False
        with patch.object(capture, "u32", api), \
                patch.object(capture, "_with_per_monitor_dpi", side_effect=lambda fn: fn()) as dpi, \
                patch.object(capture, "_capture_window_physical", return_value="image") as physical:
            assert capture.capture_window(123) == "image"
        dpi.assert_called_once()
        physical.assert_called_once_with(123)

    @pytest.mark.parametrize("print_ok,lines,success", [(False, 2, False), (True, 0, False), (True, 2, True)])
    def test_capture_checks_failures_and_ignores_alpha(self, print_ok, lines, success):
        from txrui import capture
        api, gdi = Mock(), Mock()

        def get_rect(hwnd, pointer):
            rect = pointer._obj
            rect.left = rect.top = 0
            rect.right = rect.bottom = 2
            return True

        def read_bits(dc, bitmap, first, height, buf, info, usage):
            ctypes.memmove(buf, bytes([30, 20, 10, 0]) * 4, 16)
            return lines

        api.GetWindowRect.side_effect = get_rect
        api.PrintWindow.return_value = print_ok
        gdi.SelectObject.return_value = 99
        gdi.GetDIBits.side_effect = read_bits
        with patch.object(capture, "u32", api), patch.object(capture, "gdi32", gdi):
            image = capture._capture_window_physical(123)
        if success:
            assert image.mode == "RGB"
            assert image.getpixel((0, 0)) == (10, 20, 30)
            calls = gdi.method_calls
            restore_index = next(i for i, call in enumerate(calls)
                                 if call[0] == "SelectObject" and call.args[1] == 99)
            read_index = next(i for i, call in enumerate(calls) if call[0] == "GetDIBits")
            assert restore_index < read_index
        else:
            assert image is None
        gdi.DeleteObject.assert_called_once()
        gdi.DeleteDC.assert_called_once()
        api.ReleaseDC.assert_called_once()
        if not print_ok:
            gdi.GetDIBits.assert_not_called()
