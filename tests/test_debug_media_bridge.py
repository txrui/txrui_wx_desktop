"""用模拟截图验证媒体调试接口的裁剪、筛选、结果字段及前端渲染源码。"""
import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import txrui
from txrui.webbridge import TxruiBridge

BOXES = ((0, .1, .25, .9), (.25, .2, 1, .8), (.25, 0, 1, .2))
KINDS = ("emoji", "image", "video", "file", "audio")


@pytest.fixture
def context(monkeypatch):
    shot = Image.new("RGB", (1600, 1000), "white")
    bubbles = [dict(kind=kind, x=12, y=15 + i * 40, w=80, h=30,
                    text="<img src=x onerror=alert(1)>" + "长" * 100,
                    reason="中文识别依据", confidence=.85, extra={"source": "test"},
                    **({"duration": 15} if kind == "video" else {}))
               for i, kind in enumerate(KINDS)]
    cap = SimpleNamespace(capture_window=Mock(return_value=shot),
                          find_wechat_window=Mock(return_value=123))
    ocr = SimpleNamespace(ocr_image=Mock(return_value=[{"text": "OCR"}]))
    media = SimpleNamespace(detect_media_bubbles=Mock(return_value=bubbles))
    regions = SimpleNamespace(regions_for_window=Mock(return_value=BOXES))
    scale = SimpleNamespace(active_scale=Mock(return_value=125))
    for name, module in dict(capture=cap, ocr=ocr, media=media, regions=regions, scale=scale).items():
        monkeypatch.setitem(sys.modules, f"txrui.{name}", module)
        monkeypatch.setattr(txrui, name, module, raising=False)
    bridge = TxruiBridge(SimpleNamespace(backend=SimpleNamespace(_hwnd=456)))
    return SimpleNamespace(bridge=bridge, shot=shot, bubbles=bubbles, cap=cap,
                           ocr=ocr, media=media, regions=regions)


def test_default_compatible_and_preserves_detection_fields(context):
    r = context.bridge.debug_media()
    assert r["ok"]
    assert (r["kind"], r["region"], r["label"]) == ("all", "message", "消息区")
    assert r["count"] == 5 and r["counts"] == dict.fromkeys(KINDS, 1)
    assert r["bubbles"] == context.bubbles
    assert r["bubbles"][0] is not context.bubbles[0]
    assert (r["orig_width"], r["orig_height"]) == (1200, 600)
    assert r["box"] == [400, 200, 1600, 800]
    assert (r["width"], r["height"], r["scale"]) == (960, 480, .8)
    assert r["window_size"] == [1600, 1000]
    image = Image.open(io.BytesIO(base64.b64decode(r["image"].split(",")[1])))
    assert image.size == (960, 480)
    context.cap.find_wechat_window.assert_not_called()
    context.regions.regions_for_window.assert_called_once_with(1600, 1000, 125, shot=context.shot)
    args = context.media.detect_media_bubbles.call_args.args
    assert args[0].size == (1200, 600) and args[1:] == ([{"text": "OCR"}], 125)


@pytest.mark.parametrize("kind", KINDS)
def test_filters_all_supported_types(context, kind):
    r = context.bridge.debug_media(kind)
    assert r["ok"] and r["count"] == 1 and r["counts"] == {kind: 1}
    assert r["bubbles"] == [b for b in context.bubbles if b["kind"] == kind]
    # 按类型筛选仍须调用共享媒体检测器。
    context.media.detect_media_bubbles.assert_called_once()


@pytest.mark.parametrize("region,box,label", [
    ("", [0, 0, 1600, 1000], "整窗"),
    ("session", [0, 100, 400, 900], "会话区"),
    ("message", [400, 200, 1600, 800], "消息区"),
    ("title", [400, 0, 1600, 200], "标题区"),
])
def test_selected_region_uses_shared_calibration(context, region, box, label):
    r = context.bridge.debug_media("all", region)
    assert r["ok"] and r["box"] == box and r["label"] == label
    assert (r["orig_width"], r["orig_height"]) == (box[2] - box[0], box[3] - box[1])
    if region:
        context.regions.regions_for_window.assert_called_once()
    else:
        context.regions.regions_for_window.assert_not_called()


@pytest.mark.parametrize("args", [("text",), (None,), ([],), ("all", "bad"), ("all", None), ("all", [])])
def test_invalid_arguments_fail_before_capture(context, args):
    r = context.bridge.debug_media(*args)
    assert not r["ok"] and r["error"]
    context.cap.capture_window.assert_not_called()


def test_empty_result_still_has_preview(context):
    context.media.detect_media_bubbles.return_value = []
    r = context.bridge.debug_media("emoji", "title")
    assert r["ok"] and r["count"] == 0 and r["counts"] == {} and r["bubbles"] == []
    assert r["image"].startswith("data:image/jpeg;base64,")


def test_filtered_empty_result(context):
    context.media.detect_media_bubbles.return_value = [context.bubbles[0]]
    r = context.bridge.debug_media("video")
    assert r["ok"] and r["count"] == 0 and r["counts"] == {} and r["bubbles"] == []


def test_capture_errors(context):
    context.bridge.rt.backend = None
    context.cap.find_wechat_window.return_value = None
    assert not context.bridge.debug_media()["ok"]
    context.cap.find_wechat_window.return_value = 123
    context.cap.capture_window.return_value = None
    assert not context.bridge.debug_media()["ok"]


def test_debug_media_page_controls_and_safe_renderer():
    html = (ROOT / "webui" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "webui" / "app.js").read_text(encoding="utf-8")
    for ident, label in [("btnDbgMedia", "媒体气泡检测"), ("btnDbgEmoji", "表情识别"),
                         ("btnDbgImage", "图片识别"), ("btnDbgVideo", "视频识别")]:
        assert f'id="{ident}">{label}</button>' in html
        assert f'"{ident}"' in js
    assert 'dbgRun("debug_media", [kind, $("dbgRegion").value], dbgRenderMedia)' in js
    assert 'dbgRun("debug_media", ["all", $("dbgRegion").value], dbgRenderMedia)' in js
    renderer = js.split("function dbgRenderMedia(r) {", 1)[1].split("function dbgRenderEnv", 1)[0]
    assert "innerHTML" not in renderer
    for field in ("confidence", "reason", "duration", "orig_width", "orig_height"):
        assert field in renderer
    assert "detail.textContent" in renderer and "coords.textContent" in renderer
    assert "未检出" in renderer and "依据" in renderer and "置信度" in renderer
