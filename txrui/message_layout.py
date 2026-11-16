"""按气泡颜色和横向位置判断消息归属，并计算媒体与文字框的重叠关系。"""
from __future__ import annotations


def media_contains_text(bubble: dict, box: dict) -> bool:
    """文字框至少一半面积与媒体框重叠时视为关联，使用同一裁图坐标系。"""
    left = max(bubble["x"], box["x"])
    top = max(bubble["y"], box["y"])
    right = min(bubble["x"] + bubble["w"], box["x"] + box["w"])
    bottom = min(bubble["y"] + bubble["h"], box["y"] + box["h"])
    overlap = max(0, right - left) * max(0, bottom - top)
    return overlap >= max(1, box["w"] * box["h"]) * 0.5


def text_is_self(region, item: dict) -> bool:
    """优先按气泡颜色占比判断自身消息，未命中时使用文本框中心位置。"""
    import numpy as np
    from .visual_settings import value as v, color_mask

    w, h = region.size
    x, y = max(0, int(item["x"])), max(0, int(item["y"]))
    right = min(w, int(item["x"] + item["w"]))
    bottom = min(h, int(item["y"] + item["h"]))
    if right > x and bottom > y:
        pixels = np.asarray(region.convert("RGB"), dtype=np.int16)[y:bottom, x:right]
        # 绿色气泡大部分是背景；少数绿色字形、图标不应改变归属。
        green = (color_mask(pixels, "self_color", "self_tol") if v("self_color_manual") else
                 ((pixels[:, :, 1] - pixels[:, :, 0] > v("self_gr"))
                  & (pixels[:, :, 1] - pixels[:, :, 2] > v("self_gb"))
                  & (pixels[:, :, 1] > v("self_g_min"))))
        if float(green.mean()) > v("self_fill"):
            return True
    return item["x"] + item["w"] / 2 > w * v("self_split")
