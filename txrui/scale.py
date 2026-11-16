"""按显示缩放百分比换算基准标定值，并维护生效档位和越界标记。

长度乘以缩放系数，面积乘以系数平方；颜色、宽高比和占比不在此换算。
设置生效档位时限制到支持区间；显式传给 k 的正数档位不作区间限制。
"""
from __future__ import annotations

#: 标定参考缩放百分比，用于计算长度和面积换算系数。
CALIB_SCALE = 175

#: 支持的缩放区间（百分比）。常见 Windows 缩放 100/125/150 覆盖在内。
MIN_SCALE = 100
MAX_SCALE = 175

#: 实测不到 DPI 时的兜底档位
DEFAULT_SCALE = CALIB_SCALE

_ACTIVE = DEFAULT_SCALE
#: 最近一次有效设置是否因越界而被限制。
_OUT_OF_RANGE = False


def clamp_scale(pct) -> int:
    """把任意输入钳到支持区间 [MIN_SCALE, MAX_SCALE]，返回合法档位。

    非数字输入返回 DEFAULT_SCALE。
    """
    try:
        v = int(round(float(pct)))
    except (TypeError, ValueError):
        return DEFAULT_SCALE
    if v < MIN_SCALE:
        return MIN_SCALE
    if v > MAX_SCALE:
        return MAX_SCALE
    return v


def set_active_scale(pct) -> int:
    """写入当前生效档位。

    - 非法值（非数字）→ **保持原档位不动**，不算越界。
    - 超出 [MIN_SCALE, MAX_SCALE] → 钳到边界，并置 out_of_range 标记。
    返回最终生效档位。
    """
    global _ACTIVE, _OUT_OF_RANGE
    try:
        v = int(round(float(pct)))
    except (TypeError, ValueError):
        return _ACTIVE
    if v < MIN_SCALE:
        v, _OUT_OF_RANGE = MIN_SCALE, True
    elif v > MAX_SCALE:
        v, _OUT_OF_RANGE = MAX_SCALE, True
    else:
        _OUT_OF_RANGE = False
    _ACTIVE = v
    return _ACTIVE


# 提供设置生效档位的便捷入口。
def set_active(scale: int) -> None:
    set_active_scale(scale)


def active_scale() -> int:
    return _ACTIVE


def active() -> int:
    return _ACTIVE


def out_of_range() -> bool:
    """最近一次写入的档位是否被钳制过（超出支持区间）。"""
    return _OUT_OF_RANGE


def supported() -> tuple[int, int]:
    """支持区间 (min, max)。"""
    return (MIN_SCALE, MAX_SCALE)


def k(scale: int | None = None) -> float:
    """换算系数：物理长度 = 基准档长度 x k。"""
    s = _ACTIVE if scale is None else scale
    try:
        s = float(s)
    except (TypeError, ValueError):
        s = DEFAULT_SCALE
    if s <= 0:
        s = DEFAULT_SCALE
    return s / float(CALIB_SCALE)


def px(v: float, scale: int | None = None) -> int:
    """物理像素长度换算（线性）。"""
    return int(round(v * k(scale)))


def area(v: float, scale: int | None = None) -> int:
    """物理像素面积换算（平方）。"""
    kk = k(scale)
    return max(1, int(round(v * kk * kk)))
