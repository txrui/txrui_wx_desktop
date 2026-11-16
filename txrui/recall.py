"""在当前会话中按文本定位消息，通过右键菜单尝试撤回。

目标匹配使用去空白后的子串，可用锚点选择其后的首个匹配项。
菜单识别先使用配置区域，再尝试全屏截图；确认按钮仅在识别到时点击。
成功表示已执行菜单操作，不验证撤回结果，也不提供稳定的平台消息标识。
"""
from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

#: 菜单里「撤回」的候选文案（微信各版本措辞有差异）
_RECALL_MENU_WORDS = ("撤回", "撤销")
#: 二次确认「确定」候选
_CONFIRM_WORDS = ("确定", "确认", "撤回")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def find_recall_menu_item(ocr_items: list[dict]) -> dict | None:
    """在 OCR 结果里找「撤回」菜单项。

    返回 {"text", "x", "y", "w", "h"}；找不到返回 None。
    """
    for it in (ocr_items or []):
        t = _norm(it.get("text", ""))
        if not t:
            continue
        for w in _RECALL_MENU_WORDS:
            if w in t:
                return it
    return None


def find_confirm_button(ocr_items: list[dict]) -> dict | None:
    """在 OCR 结果里找二次确认的「确定」按钮。"""
    for it in (ocr_items or []):
        t = _norm(it.get("text", ""))
        if not t:
            continue
        # 必须短且精确匹配，避免命中「撤回了一条消息」这类提示文本
        if t in ("确定", "确认", "好的", "撤回"):
            return it
    return None


def locate_message_bubble(ocr_items: list[dict], target_text: str,
                          anchor_text: str = "") -> dict | None:
    """在消息区 OCR 结果里定位目标消息气泡的文本框。

    - `target_text`：目标消息的文本（子串匹配即可）。
    - `anchor_text`：可选锚点——目标文本重复时（如「好的」多次出现），
      取锚点**之后**最近的那个，避免撤错消息。

    返回 {"text", "x", "y", "w", "h"}；找不到返回 None。
    """
    items = sorted(ocr_items or [], key=lambda i: (i.get("y", 0), i.get("x", 0)))
    tgt = _norm(target_text)
    if not tgt:
        return None
    anchor = _norm(anchor_text)
    anchor_idx = -1
    if anchor:
        for idx, it in enumerate(items):
            if anchor in _norm(it.get("text", "")):
                anchor_idx = idx
                break
    best = None
    for idx, it in enumerate(items):
        if anchor_idx >= 0 and idx <= anchor_idx:
            continue
        if tgt in _norm(it.get("text", "")):
            best = it
            break
    return best


def _ocr_scope(shot, key):
    """裁剪配置区域，OCR 结果再还原到整窗坐标。"""
    from . import ocr
    from .visual_settings import rect
    l,t,r,b = rect(key, *shot.size, (0,0,1,1))
    items = ocr.ocr_image(shot.crop((l,t,r,b)))
    return [dict(it, x=it.get("x",0)+l, y=it.get("y",0)+t) for it in items]


def recall_message(hwnd, target_text: str = "", anchor_text: str = "",
                   region=None, ocr_items: list[dict] | None = None) -> dict:
    """按文本子串定位并点击撤回菜单，可用锚点区分重复文本。

    region 为可选屏幕矩形；ocr_items 坐标应相对该消息裁图区。
    返回操作状态与错误，平台消息标识始终为空；不检查最终撤回结果。
    """
    empty = {"ok": False, "unknown": False, "platform_message_id": "", "error": ""}
    if not target_text:
        return {**empty, "error": "no_target_text:撤回需按消息内容定位"}

    try:
        import pyautogui
    except Exception as e:  # noqa: BLE001
        return {**empty, "error": f"pyautogui_unavailable:{str(e)[:80]}"}

    try:
        from . import capture as _cap
        from . import ocr as _ocr
    except Exception as e:  # noqa: BLE001
        return {**empty, "error": f"import_failed:{str(e)[:80]}"}

    if not hwnd:
        return {**empty, "error": "no_window"}

    try:
        _cap.ensure_visible(hwnd)
        _cap.foreground(hwnd)
        time.sleep(0.2)
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {**empty, "error": "capture_failed"}
        w, h = shot.size
        wr = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(hwnd))
        if not wr:
            return {**empty, "error": "no_window_rect"}
        win_l, win_t = wr[:2]
        from .visual_settings import value

        if region is None:
            from . import regions as _rg
            from . import scale as _scale
            sr, mr, _tr = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)
        else:
            mr = None
        if mr is not None:
            rl, rt, rr, rb = (int(w * mr[0]), int(h * mr[1]),
                              int(w * mr[2]), int(h * mr[3]))
        else:
            rl, rt, rr, rb = (region[0]-win_l, region[1]-win_t,
                              region[2]-win_l, region[3]-win_t)

        msg_img = shot.crop((rl, rt, rr, rb))
        items = ocr_items if ocr_items is not None else _ocr.ocr_image(msg_img)

        bubble = locate_message_bubble(items, target_text, anchor_text)
        if not bubble:
            return {**empty, "error": "not_found:消息区找不到目标消息"}

        # 屏幕坐标：区域图坐标 + 区域图左上角屏幕偏移
        bx = win_l + rl + int(bubble.get("x", 0) + bubble.get("w", 0) * value("recall_click_x"))
        by = win_t + rt + int(bubble.get("y", 0) + bubble.get("h", 0) * value("recall_click_y"))

        # 右键点开菜单
        pyautogui.rightClick(bx, by)
        time.sleep(0.8)

        # 菜单是独立顶层窗口（不在消息区内）——整窗 OCR 找菜单项
        shot2 = _cap.capture_window(hwnd)
        if shot2 is None:
            return {**empty, "error": "capture_failed_after_menu"}
        menu_items = _ocr_scope(shot2, "recall_menu")
        menu_hit = find_recall_menu_item(menu_items)
        menu_origin = (win_l, win_t)
        if not menu_hit:
            # 独立顶层菜单可能在主窗口外，全屏 OCR 坐标已经是屏幕坐标。
            try:
                menu_hit = find_recall_menu_item(_ocr.ocr_image(pyautogui.screenshot()))
                menu_origin = (0, 0)
            except Exception:
                pass
            if not menu_hit:
                return {**empty, "error": "no_recall_menu:菜单里没有「撤回」项"}
        mx = menu_origin[0] + int(menu_hit.get("x", 0) + menu_hit.get("w", 0) * value("menu_click_x"))
        my = menu_origin[1] + int(menu_hit.get("y", 0) + menu_hit.get("h", 0) * value("menu_click_y"))

        pyautogui.click(mx, my)
        time.sleep(0.8)

        # 二次确认
        try:
            shot3 = _cap.capture_window(hwnd)
            if shot3 is not None:
                conf_items = _ocr_scope(shot3, "recall_confirm")
                conf = find_confirm_button(conf_items)
                if conf:
                    cx = win_l + int(conf.get("x", 0) + conf.get("w", 0) * value("confirm_click_x"))
                    cy = win_t + int(conf.get("y", 0) + conf.get("h", 0) * value("confirm_click_y"))
                    pyautogui.click(cx, cy)
                    time.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"撤回二次确认处理异常: {e}")

        logger.info(f"[撤回] 已点击撤回: {target_text[:20]!r}")
        # 视觉端无稳定消息 ID —— core 记 no_remote_id，属预期
        return {"ok": True, "unknown": False, "platform_message_id": "",
                "error": ""}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"撤回失败: {e}")
        return {**empty, "unknown": True, "error": f"recall_exception:{str(e)[:120]}"}
