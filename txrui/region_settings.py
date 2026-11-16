"""读取并缓存手动区域和视觉参数，通过临时文件替换保存配置。

支持纯三区域字典和带版本的组合格式；保存后立即更新进程内缓存。
"""
from __future__ import annotations

import json
import math
import threading
from pathlib import Path

from .paths import app_dir

_PATH = app_dir() / "regions.json"
_LOCK = threading.RLock()
_CACHE = None
_VISUAL = {}
_KEYS = ("session", "message", "title")


def validate(regions):
    if not isinstance(regions, dict) or set(regions) != set(_KEYS):
        raise ValueError("必须提供会话区、消息区、标题区的完整边界")
    out = {}
    for key in _KEYS:
        box = regions[key]
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise ValueError("区域必须为 [左, 上, 右, 下] 四个比例")
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in box):
            raise ValueError("区域边界必须为有限数字")
        l, t, r, b = box
        if not (0 <= l < r <= 1 and 0 <= t < b <= 1):
            raise ValueError("区域边界必须在窗口范围内，且宽高大于零")
        out[key] = tuple(float(v) for v in box)
    if out["message"][1] < out["title"][3]:
        raise ValueError("消息区上边界应在标题区下边界之下，避免包含标题")
    return out


def _load():
    global _CACHE, _VISUAL
    if _CACHE is not None:
        return
    _CACHE, _VISUAL = {}, {}
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "version" in data:
            from .visual_settings import validate as validate_visual
            regions = validate(data["regions"]) if data.get("regions") else {}
            visual = validate_visual(data.get("visual", {}))
            _CACHE, _VISUAL = regions, visual
        else:
            _CACHE = validate(data)
    except (OSError, ValueError, TypeError, KeyError):
        pass


def get_regions():
    with _LOCK:
        _load()
        return dict(_CACHE)


def get_visual():
    import copy
    with _LOCK:
        _load()
        return copy.deepcopy(_VISUAL)


def save_profile(regions, visual):
    global _CACHE, _VISUAL
    from .visual_settings import validate as validate_visual
    checked = validate(regions) if regions else {}
    settings = validate_visual(visual)
    with _LOCK:
        data = {"version": 2, "regions": checked, "visual": settings}
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
        _CACHE, _VISUAL = checked, settings


def save_regions(regions):
    """保存三区域；已有视觉参数时写组合格式，否则保留纯三区域格式。"""
    global _CACHE
    checked = validate(regions)
    with _LOCK:
        _load()
        if _VISUAL:
            save_profile(checked, _VISUAL)
            return
        tmp = _PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
        _CACHE = checked


def reset_regions():
    global _CACHE, _VISUAL
    with _LOCK:
        _PATH.unlink(missing_ok=True)
        _CACHE, _VISUAL = {}, {}
