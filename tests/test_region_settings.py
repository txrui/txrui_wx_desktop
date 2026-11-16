"""验证手动区域的保存、校验、优先级及网页接口的预览与重置。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from txrui import region_settings as settings
from txrui.regions import regions_for_window

BOXES = {"session": [0.05, 0.12, 0.3, 0.95],
         "message": [0.31, 0.15, 0.99, 0.8],
         "title": [0.32, 0.04, 0.85, 0.12]}


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_PATH", tmp_path / "regions.json")
    monkeypatch.setattr(settings, "_CACHE", None)
    monkeypatch.setattr(settings, "_VISUAL", {})


def test_persist_and_reload():
    settings.save_regions(BOXES)
    settings._CACHE = None
    assert settings.get_regions() == settings.validate(BOXES)
    assert json.loads(settings._PATH.read_text()) == BOXES


def test_manual_overrides_pixel_detection_and_resizes():
    settings.save_regions(BOXES)
    for w, h in [(1500, 1000), (1000, 700)]:
        result = regions_for_window(w, h, 100, boundary_px=999, header_y=300)
        assert result == tuple(tuple(BOXES[k]) for k in ("session", "message", "title"))


def test_reset_restores_auto():
    auto = regions_for_window(1500, 1000, 100)
    settings.save_regions(BOXES)
    settings.reset_regions()
    assert regions_for_window(1500, 1000, 100) == auto
    assert not settings._PATH.exists()


@pytest.mark.parametrize("box", [[-0.1,0,1,1], [0,0,2,1], [0.5,0,0.4,1],
                                 [0,0,1,0], [0,0,float("nan"),1],
                                 [0,0,float("inf"),1], [True,0,1,1], [0,0,1]])
def test_reject_bad_coordinates(box):
    with pytest.raises(ValueError):
        settings.save_regions(dict(BOXES, session=box))
    assert not settings.get_regions()


def test_reject_title_overlap():
    with pytest.raises(ValueError, match="标题"):
        settings.save_regions(dict(BOXES, message=[0.31,0.05,0.99,0.8]))


def test_failed_write_keeps_previous_settings(monkeypatch):
    settings.save_regions(BOXES)
    with patch.object(Path, "replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            settings.save_regions(dict(BOXES, session=[0,0,0.2,0.9]))
    assert settings.get_regions() == settings.validate(BOXES)


@pytest.mark.skipif(sys.platform != "win32", reason="网页截图接口依赖 Windows")
def test_bridge_save_preview_reset_and_stale_window():
    from txrui.webbridge import TxruiBridge
    backend = SimpleNamespace(_hwnd=123, _apply_regions=Mock())
    bridge = TxruiBridge(SimpleNamespace(backend=backend))
    image = Image.new("RGB", (1500, 1000), "white")
    with patch("txrui.capture.capture_window", return_value=image):
        assert not bridge.debug_regions("save", BOXES, [1000,700])["ok"]
        assert not settings.get_regions()
        tiny = dict(BOXES, title=[0.32,0.04,0.321,0.12])
        assert not bridge.debug_regions("save", tiny, [1500,1000])["ok"]
        result = bridge.debug_regions("save", BOXES, [1500,1000])
        assert result["ok"] and result["manual"]
        assert result["regions"] == settings.validate(BOXES)
        assert result["image"].startswith("data:image/png;base64,")
        shot = bridge.debug_shot("title")
        assert shot["box"] == [480,40,1275,120]
        result = bridge.debug_regions("reset")
        assert result["ok"] and not result["manual"]
    assert backend._apply_regions.call_count == 2
