"""计算会话区、消息区和标题区边界，并从标题解析会话类型。

有效窗口优先使用手动比例标定；否则结合截图探测分隔线、标题栏和输入框。
探测缺失时使用缩放后的像素标定；无分隔线且窗口宽高比偏差较大时使用比例。
返回区域均为整窗比例，标题末尾的数字括号用于识别群聊人数。
"""
from __future__ import annotations

import re
from .visual_settings import value as _v

#: 基准缩放下用于区域换算的窗口宽高。
WINDOW_SIZE = (1300, 1610)

#: 基准档绝对像素标定：(l, t, r, b)
#   - l/t 为正：从窗口左/上边量的偏移
#   - r/b 为负：距窗口右/下边的距离（负值）
#   - r/b 为正：从窗口左/上边量的偏移
_REGION_EDGES = {
    "session": (117.0, 141.4, 543.4, -16.9),
    "message": (541.45, 207.4, -11.31, -267.7),
    "title": (539.63, 62.1, -243.36, 132.0),
}

#: 比例兜底档（标定窗口下的比例）
_REGION_RATIOS = {
    "session": (0.0900, 0.0878, 0.4180, 0.9895),
    "message": (0.4165, 0.1288, 0.9913, 0.8337),
    "title": (0.4151, 0.0386, 0.8128, 0.0820),
}

#: 窗口宽高比与标定窗口差异超过这个比例（相对值）就切到比例档
_ASPECT_TOLERANCE = 0.18

#: 竖分隔线扫描范围的模块常量；检测实际读取视觉配置。
_DIVIDER_SCAN = (0.15, 0.55)

#: 顶栏搜索范围的模块常量；检测实际读取视觉配置。
_HEADER_BAND = (0.03, 0.14)

#: 标题保留高度的参考常量；区域计算实际读取视觉配置。
_HEADER_H = 50

#: 输入区间距的参考常量；区域计算实际读取视觉配置。
_INPUT_MARGIN = 30

#: 默认区域比例，供后端初始化和无效尺寸兜底使用。
_SESSION_REGION_RATIO = _REGION_RATIOS["session"]
_MESSAGE_REGION_RATIO = _REGION_RATIOS["message"]
_TITLE_REGION_RATIO = _REGION_RATIOS["title"]


def _k(scale: int | None = None) -> float:
    from . import scale as _s  # 延迟导入避免循环
    return _s.k(scale)


def _use_ratio_mode(w: int, h: int) -> bool:
    """窗口形状与标定窗口差太多时，用比例档更稳。"""
    if w <= 0 or h <= 0:
        return True
    cw, ch = WINDOW_SIZE
    if cw <= 0 or ch <= 0:
        return True
    ref = cw / ch
    cur = w / h
    if ref <= 0:
        return True
    return abs(cur - ref) / ref > _ASPECT_TOLERANCE


def detect_divider_x(shot) -> int | None:
    """从截图探测列表/聊天区之间的细线或背景色边界。

    使用中部多行的一致横向色差，排除大块纯色背景。仅凭“某列
    颜色少”无法区分列表空白与真实分隔线，会导致裁剪起点错位。
    """
    if shot is None:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    try:
        arr = np.asarray(shot.convert("RGB"), dtype="int16")
    except Exception:
        return None
    h, w = arr.shape[0], arr.shape[1]
    if w <= 0 or h <= 0:
        return None
    lo = int(w * _v("divider_left"))
    hi = min(int(w * _v("divider_right")), w - 1)
    threshold, required = _v("edge_contrast"), _v("edge_coverage")
    if hi - lo < 4:
        return None
    # 截去顶栏、输入区，防止它们的图标/横线影响竖直边界。
    band = arr[int(h * 0.20):max(int(h * 0.20) + 1, int(h * 0.75))]
    best_x, best_score = None, 0.0
    for x in range(max(3, lo), min(hi, w - 3)):
        col = band[:, x, :].astype(float)
        left = band[:, x - 3, :].astype(float)
        right = band[:, x + 3, :].astype(float)
        # 真正细线比两边都暗；色阶则要求左右色差在大多数行持续存在。
        line = np.minimum((left - col).mean(axis=1), (right - col).mean(axis=1))
        step = (right - left).mean(axis=1)
        edge = (col - band[:, x - 1, :]).mean(axis=1)
        edge_coverage = max(float(((step >= threshold) & (edge >= threshold)).mean()),
                            float(((step <= -threshold) & (edge <= -threshold)).mean()))
        coverage = max(float((line >= threshold).mean()), edge_coverage)
        if coverage < required:
            continue
        score = coverage * 10 + max(float(np.median(line)),
                                    float(abs(np.median(step))))
        if score > best_score:
            best_score, best_x = score, x
    return best_x


def detect_header_y(shot, x0: int, x1: int,
                    scale: int | None = None) -> int | None:
    """返回标题栏下边界；候选横线或色阶须满足配置覆盖率与灰度条件。"""
    if shot is None:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    try:
        gray = np.asarray(shot.convert("L"), dtype="int16")
    except Exception:
        return None
    h, w = gray.shape[0], gray.shape[1]
    x0 = max(0, min(int(x0), w - 2))
    x1 = max(x0 + 2, min(int(x1), w))
    band = gray[:, x0:x1]
    if band.size == 0:
        return None
    # 窗口系统标题栏也有横贯面板的色阶，必须先排除它。
    # 以 DPI 像素高度限制搜索下界，不能只按整窗高度的 3% 搜索：
    # 1500x1000、100% 下系统标题栏底边约为 32px，会被误认。
    y0 = max(3, int(h * _v("header_top")), round(_v("header_min") * _k(scale)))
    y1 = min(h - 1, max(int(h * _v("header_bottom")), round(_v("header_max") * _k(scale))))
    threshold, required = _v("edge_contrast"), _v("edge_coverage")
    if y1 - y0 < 4:
        return None
    inset = max(1, band.shape[1] // 10)
    inner = band[:, inset:-inset]
    if inner.shape[1] < 2:
        return None
    for y in range(max(3, y0), min(h - 3, y1)):
        row = inner[y].astype(float)
        above = inner[y - 3].astype(float)
        below = inner[y + 3].astype(float)
        line = (above + below) / 2 - row
        step = below - above
        coverage = max(float((line >= threshold).mean()),
                       float((step >= threshold).mean()),
                       float((step <= -threshold).mean()))
        if coverage >= required and float(row.mean()) > _v("edge_gray_min") and float(row.std()) < _v("edge_std_max"):
            # 对背景色阶返回真实色阶起点，而非上方邻行的 y。
            if float((line >= threshold).mean()) < required:
                delta = abs(inner[y - 3:y + 4].astype(float)[1:]
                            - inner[y - 3:y + 4].astype(float)[:-1]).mean(axis=1)
                return y - 2 + int(delta.argmax())
            return y
    return None


def detect_input_top_y(shot, x0: int, x1: int) -> int | None:
    """探测聊天区输入框的上边框 y。

    优先寻找下半窗内横贯聊天面板的浅色边框，排除仅占少量列的
    工具栏图标和发送按钮。找不到可靠边框时返回 None，使用标定兜底。
    """
    if shot is None:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    try:
        gray = np.asarray(shot.convert("L"), dtype="int16")
    except Exception:
        return None
    h, w = gray.shape[0], gray.shape[1]
    x0 = max(0, min(int(x0), w - 2))
    x1 = max(x0 + 2, min(int(x1), w))
    band = gray[:, x0:x1]
    if band.size == 0:
        return None
    # 优先找横贯聊天面板的浅色边框。按钮/图标只占少量列，不能作为分界。
    # 输入框可能与消息区同底色，因此比较当前行与上下邻行，而非只比较均值。
    inset = max(1, band.shape[1] // 10)
    inner = band[:, inset:-inset]
    threshold, required = _v("edge_contrast"), _v("edge_coverage")
    for y in range(int(h * _v("input_scan_top")), min(h - 4, int(h * _v("input_scan_bottom")))):
        row = inner[y]
        neighbors = (inner[y - 3].astype(float) + inner[y + 3]) / 2
        contrast = neighbors - row
        if (float((contrast >= threshold).mean()) >= required
                and float(row.mean()) > _v("edge_gray_min") and float(row.std()) < _v("edge_std_max")):
            return y
    # 没有可靠的横线就回退到尺寸标定；底部发送按钮不能代表输入框顶边。
    return None


def regions_for_window(w: int, h: int, scale: int | None = None,
                       boundary_px: float | None = None,
                       shot=None, header_y: int | None = None,
                       input_top_y: int | None = None, use_manual: bool = True):
    """返回会话区、消息区和标题区的整窗比例边界。

    手动配置优先；显式边界优先于截图探测，缺失边界使用尺寸和缩放标定。
    scale 省略时读取当前生效档位；无效窗口尺寸直接返回默认比例。
    """
    if w <= 0 or h <= 0:
        return (_SESSION_REGION_RATIO, _MESSAGE_REGION_RATIO, _TITLE_REGION_RATIO)

    from .region_settings import get_regions
    manual = get_regions()
    if manual and use_manual:
        return tuple(manual[key] for key in ("session", "message", "title"))

    # ---- 1) 像素探测优先 ----
    if boundary_px is None and shot is not None:
        boundary_px = detect_divider_x(shot)
    if header_y is None and shot is not None and boundary_px:
        header_y = detect_header_y(shot, boundary_px + 10, w - 20, scale)
    if input_top_y is None and shot is not None and boundary_px:
        input_top_y = detect_input_top_y(shot, boundary_px + 10, w - 20)

    kk = _k(scale)
    ratio_mode = False
    if boundary_px is None:
        ratio_mode = _use_ratio_mode(w, h)

    out = []
    for key in ("session", "message", "title"):
        if ratio_mode:
            l_px, t_px, r_px, b_px = _REGION_RATIOS[key]
            l = l_px * w
            r = r_px * w
            t = t_px * h
            b = b_px * h
        else:
            l_px, t_px, r_px, b_px = _REGION_EDGES[key]
            l = l_px * kk
            r = (w + r_px * kk) if r_px < 0 else r_px * kk
            t = t_px * kk if t_px >= 0 else h + t_px * kk
            b = b_px * kk if b_px >= 0 else h + b_px * kk

        # 运行时探测到的列表/聊天分界线：会话区取它左边，聊天区/标题区取它右边
        if boundary_px is not None and 0 < boundary_px < w:
            if key == "session":
                r = boundary_px
            else:
                l = boundary_px

        # 探测到顶栏线：标题区 = 顶栏内，消息区 = 顶栏之下到输入框之上
        if header_y is not None and 0 < header_y < h:
            if key == "title":
                # 标题不一定紧贴下边框（高顶栏时文字可能位于上半部）。
                # 保留标定的文字起点，并在紧凑顶栏下向上扩展。
                t = max(_v("title_min_top") * kk, min(t, header_y - _v("header_text_h") * kk))
                b = float(header_y - _v("title_bottom_gap"))
                l += _v("title_left_pad") * kk
            elif key == "message":
                t = float(header_y) + _v("message_top_gap")

        # 探测到输入区顶边：消息区下界贴着它（别把"发送"按钮文字读进消息）
        # 注意：**覆盖**而非取 min —— 运行时探测比静态标定准。
        if input_top_y is not None and 0 < input_top_y < h and key == "message":
            # 已定位输入框真实顶边，只留少量边框间距，避免裁掉底部新消息。
            b = float(input_top_y - _v("message_bottom_gap"))

        # 探测到分隔线时，会话区纵向放宽到整个列表（顶部从 0 起算）
        if boundary_px is not None and key == "session":
            t = 0.0
            b = float(h)

        t = min(max(t, 0.0), max(0.0, h - 8.0 * kk))
        b = min(max(b, t + 8.0 * kk), float(h))
        l = min(max(l, 0.0), max(0.0, r - 8.0 * kk))
        r = min(max(r, l + 8.0 * kk), float(w))
        out.append((l / w, t / h, r / w, b / h))
    return tuple(out)


_TITLE_GROUP_RE = re.compile(r"^(?P<name>.+?)\s*[\(（]\s*(?P<count>\d+)\s*[\)）]\s*$")

#: 事件和发送流程共用的私信、群聊类型标记。
CHAT_TYPE_PRIVATE = "private"
CHAT_TYPE_GROUP = "group"


def parse_title(title: str):
    """解析末尾数字括号，返回去人数后缀的会话名、群聊标记和人数。

    支持中英文括号及括号内空白；没有匹配后缀时按私信返回。
    """
    if not title:
        return "", False, None
    raw = str(title).strip()
    m = _TITLE_GROUP_RE.match(raw)
    if m:
        name = m.group("name").strip()
        return (name or raw), True, int(m.group("count"))
    return raw, False, None


def detect_chat_type(title: str, *, is_group: bool | None = None,
                     member_count: int | None = None) -> dict:
    """返回会话类型、群聊标记、人数和判定原因。

    显式群聊标记直接生效；显式私信且未给人数时直接按私信返回。
    其余情况解析标题人数后缀，无后缀则按私信处理。
    """
    raw = str(title or "").strip()
    if is_group is True:
        return {"chat_type": CHAT_TYPE_GROUP, "is_group": True,
                "member_count": member_count, "reason": "显式标记为群聊"}
    if is_group is False and member_count is None:
        return {"chat_type": CHAT_TYPE_PRIVATE, "is_group": False,
                "member_count": None, "reason": "显式标记为私信"}

    name, parsed_group, parsed_count = parse_title(raw)
    if parsed_group:
        count = member_count if member_count is not None else parsed_count
        return {"chat_type": CHAT_TYPE_GROUP, "is_group": True,
                "member_count": count,
                "reason": f"标题末尾人数后缀（{name}）"}
    # 标题里带括号但不是人数（如「产品(研发)」）→ 仍是私信
    return {"chat_type": CHAT_TYPE_PRIVATE, "is_group": False,
            "member_count": None,
            "reason": "标题无人数后缀，按私信处理"}


def chat_type_label(chat_type: str) -> str:
    """会话类型 -> 中文标签（前端/日志共用一份口径）。"""
    t = str(chat_type or "").strip().lower()
    if t == CHAT_TYPE_GROUP:
        return "群聊"
    if t == CHAT_TYPE_PRIVATE:
        return "私信"
    return "未知"
