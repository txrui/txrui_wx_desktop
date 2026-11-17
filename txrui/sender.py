"""通过输入框和剪贴板发送文本或文件，并提供可选语音发送入口。

调用方负责先切换到目标会话；本模块的 chat 参数不用于定位会话。
成功仅表示界面操作完成，不校验微信是否送达。音频优先尝试虚拟声卡通道，
不可用或失败时按文件发送，并返回实际使用的方式。
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)
#: 面板中心距窗口底（按基准档标定，实际物理距离由 scale.px 按当前缩放换算）
_INPUT_FROM_BOTTOM = 149


def input_box_rect(hwnd):
    from . import capture as _cap
    win = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(hwnd))
    if not win:
        return None
    rl, rt, w, h = win
    from .visual_settings import overrides
    box = overrides().get("input")
    if box:
        l, t, r, b = (round(v*d) for v,d in zip(box,(w,h,w,h)))
        return (rl+l, rt+t, r-l, b-t)
    from .scale import px as _px
    cx = rl + int(w * 0.70)  # 消息区中线附近
    cy = rt + h - _px(_INPUT_FROM_BOTTOM)
    bw, bh = max(_px(120), int(w * 0.45)), _px(40)
    return (cx - bw // 2, cy - bh // 2, bw, bh)


def configured_point(hwnd, key):
    from . import capture as cap
    from .visual_settings import overrides
    point = overrides().get(key)
    if point is None:
        return None
    win = cap._with_per_monitor_dpi(lambda: cap.window_rect(hwnd))
    if not win:
        return None
    x,y,w,h = win
    return (x + min(w-1,round(point[0]*w)), y + min(h-1,round(point[1]*h)))


def input_focus_point(hwnd):
    point = configured_point(hwnd, "input_focus")
    if point is not None:
        return point
    rect = input_box_rect(hwnd)
    return (rect[0]+rect[2]//2,rect[1]+rect[3]//2) if rect else None


def _submit(hwnd):
    """所有文本/媒体发送使用同一触发设置；仅实际发送流程调用。"""
    import pyautogui
    from .visual_settings import value
    mode = value("send_mode")
    if mode == "click":
        point = configured_point(hwnd, "send_button")
        if point is None:
            raise ValueError("点击发送模式需要先手动标定发送按钮位置")
        pyautogui.click(*point)
    elif mode == "ctrl_enter":
        pyautogui.hotkey("ctrl", "enter")
    else:
        pyautogui.press("enter")


def _focus_input(hwnd) -> bool:
    """定位并点击输入框（聚焦）。"""
    try:
        import pyautogui
        from . import capture as _cap
        point = input_focus_point(hwnd)
        if point is None:
            logger.error("无法定位输入框")
            return False
        _cap.foreground(hwnd)
        pyautogui.click(*point)
        time.sleep(0.3)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"聚焦输入框失败: {e}")
        return False


def send_text(hwnd, chat: str, text: str) -> bool:
    try:
        import pyautogui
        if not _focus_input(hwnd):
            return False
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        _submit(hwnd)
        return True
    except Exception as e:
        logger.error(f"发送失败: {e}")
        return False


def send_media_file(hwnd, chat: str, file_path: str, enter: bool = True) -> bool:
    """将本地文件写入剪贴板并粘贴，enter 为真时按配置触发发送。

    返回真仅表示操作完成；enter 为假时只粘贴，不触发发送。
    """
    if not file_path or not os.path.isfile(file_path):
        logger.error(f"发送媒体失败：文件不存在 {file_path!r}")
        return False
    try:
        import pyautogui
    except Exception as e:  # noqa: BLE001
        logger.error(f"发送媒体失败：pyautogui 不可用: {e}")
        return False

    from . import media_grab as _mg
    if not _mg.copy_to_clipboard_file(file_path):
        logger.error("发送媒体失败：写剪贴板文件失败（需 pywin32）")
        return False
    if not _focus_input(hwnd):
        return False
    try:
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
        if enter:
            _submit(hwnd)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"发送媒体失败: {e}")
        return False


def send_image_file(hwnd, image_path: str, enter: bool = True) -> bool:
    """将图片作为剪贴板位图粘贴发送，避免按 CF_HDROP 当作普通文件发送。"""
    if not image_path or not os.path.isfile(image_path):
        logger.error(f"发送图片失败：文件不存在 {image_path!r}")
        return False
    try:
        import pyautogui
        from PIL import Image
        from . import media_grab as _mg
        with Image.open(image_path) as image:
            if not _mg.copy_image_to_clipboard(image):
                logger.error("发送图片失败：写入剪贴板位图失败")
                return False
        if not _focus_input(hwnd):
            return False
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.4)
        if enter:
            _submit(hwnd)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"发送图片失败: {e}")
        return False


def send_image_bytes(hwnd, data: bytes, suffix: str = ".png") -> bool:
    """将图片字节写入临时图片文件后，按图片格式粘贴发送并清理临时文件。"""
    if not data:
        logger.error("发送图片失败：图片字节为空")
        return False
    from . import media_grab as _mg
    path = _mg.save_temp(data, suffix=suffix)
    try:
        return send_image_file(hwnd, path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def send_media_bytes(hwnd, chat: str, data: bytes, suffix: str = ".png",
                     filename: str = "") -> bool:
    """将字节保存为指定后缀的临时文件后发送，并尝试删除；filename 未使用。"""
    if not data:
        logger.error("发送媒体失败：字节为空")
        return False
    from . import media_grab as _mg
    path = _mg.save_temp(data, suffix=suffix)
    try:
        return send_media_file(hwnd, chat, path)
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def send_voice_file(hwnd, chat: str, audio_path: str) -> tuple[bool, str]:
    """优先通过虚拟声卡发送语音，失败时按文件发送。

    返回操作是否完成及方式标记，区分语音、文件降级和失败。
    """
    if not audio_path or not os.path.isfile(audio_path):
        return False, f"音频文件不存在: {audio_path!r}"
    # 路线 A：真实语音通道（可选依赖）
    try:
        from . import voice_send as _vs
        if _vs.is_available():
            if _vs.send_voice(hwnd, audio_path):
                return True, "voice"
            logger.warning("[语音] 真语音通道失败，降级为文件")
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[语音] 真语音通道异常，降级为文件: {e}")
    # 路线 B：文件降级
    if send_media_file(hwnd, chat, audio_path):
        return True, "file_fallback"
    return False, "failed"
