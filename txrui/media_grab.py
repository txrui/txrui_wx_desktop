"""获取剪贴板媒体、查找接收文件，并处理屏幕矩形裁剪和临时文件。

图片通过查看器复制；只有检测到查看器后才尝试关闭，避免误操作主窗口。
文件查找仅扫描候选目录的直接子文件，按归一化显示名包含匹配。
对外矩形使用屏幕物理坐标；与区域图坐标的转换需显式传入区域原点。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time

logger = logging.getLogger(__name__)

#: 微信「图片和视频」查看器窗口标题
VIEWER_TITLE = "图片和视频"

#: 微信默认接收文件目录（相对用户目录的候选）
_FILE_DIR_CANDIDATES = (
    os.path.join("Documents", "WeChat Files"),
    os.path.join("Documents", "xwechat_files"),
    os.path.join("Documents", "WeChat Files (xwechat)"),
)

#: 文件名先匹配常见扩展名，再尝试通用字母数字后缀。
_FILE_TOKEN_RE = re.compile(
    r"[\w一-鿿][\w一-鿿\-.+()（）]*?"
    r"\.(?:docx?|xlsx?|pptx?|pdf|txt|md|html?|json|csv|zip|rar|7z|png|jpe?g|gif|mp4|mp3)",
    re.I)
_FILE_TOKEN_LOOSE_RE = re.compile(
    r"[\w一-鿿][\w一-鿿\-.+()（）]+?"
    r"\.(?:[A-Za-z][A-Za-z0-9]{1,4})(?![A-Za-z0-9])")


# ---------------------------------------------------------------- 文件名解析

def extract_file_token(text: str) -> str:
    """提取首个候选文件名，优先匹配常见扩展名，避免混入文件大小文字。"""
    toks = _FILE_TOKEN_RE.findall(text or "")
    if toks:
        return toks[0]
    toks = _FILE_TOKEN_LOOSE_RE.findall(text or "")
    return toks[0] if toks else ""


def normalize_display_name(name: str) -> str:
    """移除文件名中的空白、下划线和连字符，供包含匹配使用。"""
    s = str(name or "").strip()
    return re.sub(r"[\s_\-]+", "", s)


# ---------------------------------------------------------------- 坐标换算

def to_screen_rect(rect, origin: tuple[int, int]) -> tuple[int, int, int, int]:
    """区域图坐标 -> 屏幕物理坐标。origin = 区域图左上角的屏幕坐标。"""
    l, t, r, b = rect
    return (origin[0] + int(l), origin[1] + int(t),
            origin[0] + int(r), origin[1] + int(b))


def from_screen_rect(rect, origin: tuple[int, int]) -> tuple[int, int, int, int]:
    """屏幕物理坐标 -> 区域图坐标。"""
    l, t, r, b = rect
    return (int(l) - origin[0], int(t) - origin[1],
            int(r) - origin[0], int(b) - origin[1])


# ---------------------------------------------------------------- 剪贴板

def _clipboard_image_bytes() -> bytes | None:
    """读剪贴板位图（CF_DIB）→ PNG 字节。"""
    try:
        from PIL import ImageGrab
        grabbed = ImageGrab.grabclipboard()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"读剪贴板失败: {e}")
        return None
    if grabbed is None:
        return None
    if isinstance(grabbed, (list, tuple)):
        return None  # 文件型剪贴板走 _clipboard_file_bytes
    try:
        import io
        buf = io.BytesIO()
        grabbed.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"剪贴板位图转 PNG 失败: {e}")
        return None


def _clipboard_file_bytes() -> bytes | None:
    """读剪贴板文件（CF_HDROP）→ 文件字节。"""
    try:
        from PIL import ImageGrab
        grabbed = ImageGrab.grabclipboard()
    except Exception:
        return None
    if not isinstance(grabbed, (list, tuple)):
        return None
    for x in grabbed:
        if isinstance(x, str) and os.path.isfile(x):
            try:
                with open(x, "rb") as f:
                    return f.read()
            except Exception as e:  # noqa: BLE001
                logger.debug(f"读剪贴板文件失败: {e}")
    return None


# ---------------------------------------------------------------- 查看器

def _find_viewer_window() -> int | None:
    """找「图片和视频」查看器窗口句柄（顶层可见窗口）。"""
    from . import capture as _cap
    import ctypes
    import ctypes.wintypes as wt

    found: list[int] = []

    @_cap._WNDENUMPROC
    def _cb(hwnd, _lp):
        if not _cap.u32.IsWindowVisible(hwnd):
            return True
        title = _cap.window_title(hwnd).strip()
        if title == VIEWER_TITLE:
            found.append(hwnd)
            return False
        return True

    try:
        _cap.u32.EnumWindows(_cb, 0)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"枚举查看器窗口失败: {e}")
    return found[0] if found else None


def _close_viewer(hwnd) -> None:
    """关闭查看器（只关已确认存在的查看器窗口，不碰微信主窗口）。"""
    try:
        import pyautogui
        _cap_fg(hwnd)
        pyautogui.press("esc")
        time.sleep(0.3)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"关闭查看器失败: {e}")


def _cap_fg(hwnd) -> None:
    from . import capture as _cap
    try:
        _cap.foreground(hwnd)
    except Exception:
        pass


# ---------------------------------------------------------------- 原图获取

def grab_original_image(screen_rect, grab_rect=None) -> bytes | None:
    """点击屏幕矩形内的配置位置，从图片查看器复制媒体字节。

    未检测到查看器时返回空值且不按退出键；检测到后在结束时尝试关闭。
    grab_rect 参数当前未使用，复制结果优先取剪贴板文件，其次取位图。
    """
    try:
        import pyautogui
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pyautogui 不可用，无法取原图: {e}")
        return None

    l, t, r, b = screen_rect
    if r <= l or b <= t:
        return None
    try:
        from .visual_settings import value
        pyautogui.click(int(l+(r-l)*value("media_click_x")),
                        int(t+(b-t)*value("media_click_y")))
        time.sleep(1.0)  # 等查看器弹出
    except Exception as e:  # noqa: BLE001
        logger.warning(f"点击图片气泡失败: {e}")
        return None

    viewer = _find_viewer_window()
    if not viewer:
        # 没有查看器 = 这不是图片（可能是表情包/视频），调用方走裁剪兜底
        logger.debug("未打开查看器（非图片气泡？）")
        return None

    data = None
    try:
        _cap_fg(viewer)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.6)
        data = _clipboard_file_bytes() or _clipboard_image_bytes()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"复制原图失败: {e}")
    finally:
        # 查看器确认存在才关
        _close_viewer(viewer)
    if data:
        logger.info(f"[原图] 取到 {len(data)} 字节")
    else:
        logger.warning("[原图] 剪贴板为空（复制失败）")
    return data


def crop_region_bytes(backend, screen_rect, pad: int = 0) -> bytes | None:
    """截微信主窗口当前帧，按屏幕矩形裁剪 → PNG 字节（表情包/视频缩略图路线）。

    不点任何东西：表情包点击会改变布局，视频缩略图点击会开始播放。
    """
    try:
        import pyautogui
        from . import capture as _cap
        hwnd = backend._hwnd
        if not hwnd:
            return None
        _cap.ensure_visible(hwnd)
        wr = _cap.window_rect(hwnd)
        if not wr:
            return None
        _cap.foreground(hwnd)
        time.sleep(0.15)
        shot = pyautogui.screenshot(region=wr)
        l, t, r, b = screen_rect
        l2 = max(0, l - wr[0] - pad)
        t2 = max(0, t - wr[1] - pad)
        r2 = min(shot.width, r - wr[0] + pad)
        b2 = min(shot.height, b - wr[1] + pad)
        if r2 - l2 < 8 or b2 - t2 < 8:
            logger.debug("裁剪矩形越界")
            return None
        crop = shot.crop((l2, t2, r2, b2))
        import io
        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"裁剪媒体失败: {e}")
        return None


# ---------------------------------------------------------------- 文件定位

def _file_dirs() -> list[str]:
    """微信接收文件目录候选列表。"""
    home = os.path.expanduser("~")
    out = []
    for rel in _FILE_DIR_CANDIDATES:
        p = os.path.join(home, rel)
        if os.path.isdir(p):
            out.append(p)
    # 也支持自定义：环境变量 WECHAT_FILE_DIRS（逗号分隔）
    env = os.getenv("WECHAT_FILE_DIRS", "")
    for p in re.split(r"[,;|]", env):
        p = p.strip()
        if p and os.path.isdir(p):
            out.append(p)
    return out


def find_file_on_disk(display_name: str, max_scan: int = 4000) -> str | None:
    """查找文件名包含归一化显示名的直接子文件，不递归遍历目录。

    按创建时间和括号编号选择最新候选；每个目录限制扫描数量。
    """
    name = str(display_name or "").strip()
    if not name:
        return None
    norm = normalize_display_name(name)
    if not norm:
        return None
    best = None
    best_key = None
    for d in _file_dirs():
        try:
            entries = []
            with os.scandir(d) as it:
                for i, entry in enumerate(it):
                    if i > max_scan:
                        break
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    entries.append(entry)
        except Exception:
            continue
        for entry in entries:
            ename = entry.name
            if norm not in normalize_display_name(ename):
                continue
            try:
                st = entry.stat()
            except Exception:
                continue
            # 优先选择创建时间较新的文件，同一时刻取括号编号较大者。
            m = re.search(r"\((\d+)\)", ename)
            seq = int(m.group(1)) if m else 0
            key = (st.st_ctime, seq)
            if best_key is None or key > best_key:
                best_key = key
                best = entry.path
    if best:
        logger.info(f"[文件] 定位成功: {best}")
    else:
        logger.info(f"[文件] 未在接收目录找到 {name!r}")
    return best


def read_file_bytes(path: str, max_bytes: int = 20 * 1024 * 1024) -> bytes | None:
    """读文件本体（限大小）。"""
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            logger.warning(f"[文件] 超过大小上限，跳过: {size} > {max_bytes}")
            return None
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[文件] 读取失败: {e}")
        return None


# ---------------------------------------------------------------- 临时文件

def save_temp(data: bytes, suffix: str = ".png") -> str:
    """落临时文件（发送侧复用）。"""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def copy_to_clipboard_file(path: str) -> bool:
    """把本地文件放进剪贴板（微信粘贴发送图片/文件用）。"""
    try:
        import win32clipboard
        import win32con
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pywin32 不可用，无法写剪贴板文件: {e}")
        return False
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, path)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"写剪贴板文件失败: {e}")
        return False


def copy_image_to_clipboard(image) -> bool:
    """把 PIL Image 放进剪贴板（位图）。"""
    try:
        import io
        import win32clipboard
        import win32con
        from PIL import ImageGrab
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pywin32/PIL 不可用，无法写剪贴板位图: {e}")
        return False
    try:
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        data = buf.getvalue()
        import ctypes
        GMEM_MOVEABLE = 0x0002
        hmem = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = ctypes.windll.kernel32.GlobalLock(hmem)
        ctypes.memmove(ptr, data, len(data))
        ctypes.windll.kernel32.GlobalUnlock(hmem)
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, hmem)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"写剪贴板位图失败: {e}")
        return False


def mime_for_path(path: str) -> str:
    """按文件扩展名返回媒体类型，未知后缀使用通用二进制类型。"""
    ext = os.path.splitext(path or "")[1].lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
        ".amr": "audio/amr", ".ogg": "audio/ogg",
        ".pdf": "application/pdf", ".txt": "text/plain",
    }.get(ext, "application/octet-stream")
