"""封装微信窗口查找、前台切换、物理尺寸调整和 Win32 截图。

测量和截图可在同一线程级显示缩放上下文中执行；截图失败返回空值，
位图和设备上下文在退出时释放。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time

from PIL import Image

logger = logging.getLogger(__name__)

u32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        u32.SetProcessDPIAware()
    except Exception:
        pass

_HANDLE = ctypes.c_void_p
_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
# 查询期间使用逐显示器缩放上下文，避免进程级缩放虚拟化影响坐标和 DPI。
# 调用结束后恢复线程原上下文。
_PMV2_CONTEXT = ctypes.c_void_p(-4)


def _with_per_monitor_dpi(fn):
    try:
        u32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        old = u32.SetThreadDpiAwarenessContext(_PMV2_CONTEXT)
        if not old:
            return fn()
        try:
            return fn()
        finally:
            u32.SetThreadDpiAwarenessContext(old)
    except Exception:
        return fn()


def _dpi_to_scale_pct(dpi: int) -> int:
    if not dpi:
        return 0
    return round(int(dpi) * 100 / 96)


def monitor_dpi_scale(hwnd=None) -> int:
    """返回显示器缩放百分比；显示器查询失败时尝试窗口 DPI，均失败则返回零。"""
    def _query_monitor():
        try:
            u32.MonitorFromWindow.restype = _HANDLE
            u32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
            hmon = u32.MonitorFromWindow(hwnd if hwnd else 0, 2 if hwnd else 1)
            if hmon:
                dx = wt.UINT()
                dy = wt.UINT()
                hr = ctypes.windll.shcore.GetDpiForMonitor(
                    ctypes.c_void_p(hmon), 0, ctypes.byref(dx), ctypes.byref(dy))
                if hr == 0 and dx.value:
                    return _dpi_to_scale_pct(dx.value)
        except Exception:
            pass
        return None

    val = _with_per_monitor_dpi(_query_monitor)
    if val:
        return val
    try:
        if hwnd:
            dpi = u32.GetDpiForWindow(hwnd)
            if dpi:
                return _dpi_to_scale_pct(dpi)
    except Exception:
        pass
    return 0
# 显式声明指针宽度和参数类型，防止 ctypes 将 64 位句柄截断为整数。
u32.GetWindowDC.restype = _HANDLE
u32.GetWindowDC.argtypes = [wt.HWND]
u32.ReleaseDC.restype = wt.INT
u32.ReleaseDC.argtypes = [wt.HWND, _HANDLE]
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
gdi32.CreateCompatibleDC.restype = _HANDLE
gdi32.CreateCompatibleDC.argtypes = [_HANDLE]
gdi32.CreateCompatibleBitmap.restype = _HANDLE
gdi32.CreateCompatibleBitmap.argtypes = [_HANDLE, wt.INT, wt.INT]
gdi32.SelectObject.restype = _HANDLE
gdi32.SelectObject.argtypes = [_HANDLE, _HANDLE]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteObject.argtypes = [_HANDLE]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [_HANDLE]
gdi32.GetDIBits.restype = wt.INT
gdi32.GetDIBits.argtypes = [
    _HANDLE, _HANDLE, wt.UINT, wt.UINT, ctypes.c_void_p,
    ctypes.c_void_p, wt.UINT]
# PrintWindow 属于 user32；同时在 gdi32 对象上提供函数别名。
gdi32.PrintWindow = u32.PrintWindow
u32.PrintWindow.restype = wt.BOOL
u32.PrintWindow.argtypes = [wt.HWND, _HANDLE, wt.UINT]
u32.SetForegroundWindow.restype = wt.BOOL
u32.SetForegroundWindow.argtypes = [wt.HWND]
u32.GetForegroundWindow.restype = _HANDLE
u32.GetForegroundWindow.argtypes = []
u32.IsIconic.restype = wt.BOOL
u32.IsIconic.argtypes = [wt.HWND]
u32.IsWindowVisible.restype = wt.BOOL
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.ShowWindow.restype = wt.BOOL
u32.ShowWindow.argtypes = [wt.HWND, wt.INT]
u32.IsZoomed.restype = wt.BOOL
u32.IsZoomed.argtypes = [wt.HWND]
u32.SetWindowPos.restype = wt.BOOL
u32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, wt.INT, wt.INT, wt.INT, wt.INT, wt.UINT]
u32.GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, wt.INT]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.GetWindowThreadProcessId.restype = wt.DWORD
u32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]
u32.keybd_event.restype = None
u32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_void_p]
_k32 = ctypes.windll.kernel32
_k32.OpenProcess.restype = _HANDLE
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.QueryFullProcessImageNameW.argtypes = [
    _HANDLE, wt.DWORD, ctypes.c_wchar_p, ctypes.POINTER(wt.DWORD)]
_k32.CloseHandle.argtypes = [_HANDLE]

_PROCESS_NAMES = ("weixin.exe", "wechat.exe")
_TITLE_EXACT = ("微信", "wechat")


def window_title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def process_basename(pid: int) -> str:
    if not pid:
        return ""
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        k32.CloseHandle(h)
        return buf.value.rsplit("\\", 1)[-1].lower() if ok else ""
    except Exception:
        return ""


def pick_wechat_window(candidates) -> int | None:
    def _exact(c):
        return c[1].strip().lower() in _TITLE_EXACT
    for pool in ([c for c in candidates if (c[2] or "") in _PROCESS_NAMES],
                 [c for c in candidates if _exact(c)]):
        if not pool:
            continue
        exact = [c for c in pool if _exact(c)]
        return max(exact or pool, key=lambda c: c[3])[0]
    return None


def find_wechat_window():
    out: list = []

    @_WNDENUMPROC
    def _cb(hwnd, _lp):
        if not u32.IsWindowVisible(hwnd):
            return True
        title = window_title(hwnd).strip()
        if not title:
            return True
        pid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = max(0, (rect.right - rect.left) * (rect.bottom - rect.top))
        out.append((hwnd, title, process_basename(int(pid.value)), area))
        return True

    u32.EnumWindows(_cb, 0)
    return pick_wechat_window(out)


def ensure_visible(hwnd) -> bool:
    if not hwnd:
        return False
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)
        time.sleep(0.3)
    return True


def resize_wechat_window(hwnd, width: int = 1500, height: int = 1000) -> bool:
    """窗口尺寸可调整时保持位置和焦点；最小化或最大化状态先还原。"""
    if not hwnd or width <= 0 or height <= 0:
        return False

    def _resize():
        if u32.IsIconic(hwnd) or u32.IsZoomed(hwnd):
            u32.ShowWindow(hwnd, 9)  # 还原最小化或最大化窗口。
            time.sleep(0.3)
        rect = window_rect(hwnd)
        if rect is None:
            return False
        if rect[2:] == (width, height):
            return True
        # 仅调整尺寸，保持位置、层叠顺序和焦点。
        if not u32.SetWindowPos(hwnd, None, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010):
            logger.warning("微信窗口调整失败，目标=%sx%s", width, height)
            return False
        time.sleep(0.3)  # 等待微信完成布局，后续截图重新计算识别区域
        actual = window_rect(hwnd)
        if actual is None or actual[2:] != (width, height):
            logger.warning("微信窗口尺寸未达到目标 %sx%s，实际=%s", width, height,
                           actual[2:] if actual else None)
            return False
        logger.info("微信窗口已自动调整为 %sx%s 像素", width, height)
        return True

    return bool(_with_per_monitor_dpi(_resize))


def foreground(hwnd) -> bool:
    try:
        if u32.GetForegroundWindow() == hwnd:
            return True
        try:
            u32.keybd_event(0x12, 0, 0, 0)
            u32.keybd_event(0x12, 0, 2, 0)
        except Exception:
            pass
        u32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        return True
    except Exception as e:
        logger.warning(f"置前失败: {e}")
        return False


def window_rect(hwnd):
    if not hwnd:
        return None
    r = wt.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    return (r.left, r.top, w, h) if w > 0 and h > 0 else None


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def capture_window(hwnd) -> Image.Image | None:
    """测量窗口并在同一物理像素上下文截图；无句柄或窗口最小化时返回空值。"""
    if not hwnd or u32.IsIconic(hwnd):
        return None
    return _with_per_monitor_dpi(lambda: _capture_window_physical(hwnd))


def _capture_window_physical(hwnd) -> Image.Image | None:
    rect = wt.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hdc_win = u32.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        if not hdc_mem:
            return None
        try:
            hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
            if not hbmp:
                return None
            old_bitmap = gdi32.SelectObject(hdc_mem, hbmp)
            try:
                if not old_bitmap or old_bitmap == ctypes.c_void_p(-1).value:
                    return None
                ok = u32.PrintWindow(hwnd, hdc_mem, 2)
                if not ok:
                    logger.warning("PrintWindow 失败 hwnd=0x%x %sx%s，丢弃无效截图", hwnd, w, h)
                    return None
                # GetDIBits 要求目标位图未选入 DC；先恢复原位图。
                gdi32.SelectObject(hdc_mem, old_bitmap)
                bih = _BIH()
                bih.biSize = ctypes.sizeof(_BIH)
                bih.biWidth, bih.biHeight, bih.biPlanes, bih.biBitCount = w, -h, 1, 32
                buf = ctypes.create_string_buffer(w * h * 4)
                lines = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bih), 0)
                if lines != h:
                    logger.warning("GetDIBits 失败 hwnd=0x%x，读取行数=%s/%s", hwnd, lines, h)
                    return None
                # GDI 的第 4 字节不是有效 alpha；直接输出不透明 RGB，避免预览透明。
                return Image.frombytes("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
            finally:
                if old_bitmap and old_bitmap != ctypes.c_void_p(-1).value:
                    gdi32.SelectObject(hdc_mem, old_bitmap)
                gdi32.DeleteObject(hbmp)
        finally:
            gdi32.DeleteDC(hdc_mem)
    finally:
        u32.ReleaseDC(hwnd, hdc_win)
