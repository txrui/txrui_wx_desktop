"""按配置颜色和八连通区域面积识别未读红点，不调用文字识别。"""
from __future__ import annotations

from PIL import Image
from .visual_settings import value as _v

_BADGE_RED = (250, 81, 81)
_BADGE_TOL = 5
_BADGE_AREA_MIN = 60
_BADGE_AREA_MAX = 1000
_BADGE_CLICK_OFFSET_X = 45
_BADGE_ROW_TOL = 40


def detect_red_clusters(shot: Image.Image, region, grid: int = 20,
                        min_hits: int = 3):
    """筛选指定比例区域内的红色八连通块，按缩放后的面积阈值返回整窗像素框。

    返回框的右、下边为末个命中像素；grid 和 min_hits 参数当前未使用。
    """
    if shot is None:
        return []
    from .scale import area as _area
    w, h = shot.size
    sl, st, sr, sb = int(w * region[0]), int(h * region[1]), int(w * region[2]), int(h * region[3])
    crop = shot.convert("RGB").crop((sl, st, sr, sb))
    rw, rh = crop.size
    if rw <= 0 or rh <= 0:
        return []
    try:
        import numpy as np
        arr = np.asarray(crop)
        r = arr[:, :, 0].astype("int16")
        g = arr[:, :, 1].astype("int16")
        b = arr[:, :, 2].astype("int16")
        color, tol = _v("badge_color"), _v("badge_tol")
        mask = ((abs(r - color[0]) <= tol)
                & (abs(g - color[1]) <= tol)
                & (abs(b - color[2]) <= tol))
        ys, xs = np.where(mask)
    except Exception:
        return []
    if len(ys) == 0:
        return []
    import numpy as _np
    seen = _np.zeros((rh, rw), dtype=bool)
    out: list = []
    lo, hi = _area(_v("badge_area_min")), _area(_v("badge_area_max"))
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if seen[sy, sx]:
            continue
        stack = [(sy, sx)]
        seen[sy, sx] = True
        n = 0
        minx = maxx = sx
        miny = maxy = sy
        while stack:
            cy, cx = stack.pop()
            n += 1
            minx, maxx = min(minx, cx), max(maxx, cx)
            miny, maxy = min(miny, cy), max(maxy, cy)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < rh and 0 <= nx < rw and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        if lo <= n <= hi:
            out.append((sl + minx, st + miny, sl + maxx, st + maxy))
    return sorted(out)


def color_close(a, b, tol: int = 12) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))
