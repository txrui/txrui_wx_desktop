"""通过 VB-CABLE 虚拟声卡播放音频，并以右 Alt 触发微信录音。

依赖音频库和可用的播放、录音端点；环回电平或默认录音设备校验失败时中止。
录音操作结束后尝试恢复三类默认录音设备；成功返回仅表示发送操作完成。
"""
from __future__ import annotations

import ctypes
import logging
import time

logger = logging.getLogger(__name__)

u32 = ctypes.windll.user32

_PUL = ctypes.POINTER(ctypes.c_ulong)
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_INPUT_KEYBOARD = 1
_VK_RMENU = 0xA5
_SCAN_ALT = 0x38


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", _PUL)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", _PUL)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT),
                ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]


def _send_kb(vk, scan, flags):
    inp = _INPUT(type=_INPUT_KEYBOARD)
    inp.union.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0,
                               dwExtraInfo=None)
    n = u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    return n == 1


def alt_down(right=True) -> bool:
    """注入带扫描码的 Alt 按下事件，右 Alt 额外设置扩展键标记。"""
    if right:
        return _send_kb(_VK_RMENU, _SCAN_ALT, _KEYEVENTF_EXTENDEDKEY)
    return _send_kb(0xA4, _SCAN_ALT, 0)


def alt_up(right=True) -> bool:
    if right:
        return _send_kb(_VK_RMENU, _SCAN_ALT,
                        _KEYEVENTF_EXTENDEDKEY | _KEYEVENTF_KEYUP)
    return _send_kb(0xA4, _SCAN_ALT, _KEYEVENTF_KEYUP)


def _capsule_green_count(arr) -> int:
    """在配置的录音提示区域统计匹配像素，支持指定颜色或绿色通道阈值。"""
    from .visual_settings import value as v, rect, color_mask
    h, w = arr.shape[:2]
    l,t,r,bottom = rect("voice_pill", w, h, (.5,.86,.95,.99))
    region = arr[t:bottom, l:r].astype("int16")
    r, g, b = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    mask = (color_mask(region, "voice_color", "voice_tol") if v("voice_color_manual") else
            ((g > v("voice_g_min")) & (g-r > v("voice_gr")) & (g-b > v("voice_gb"))))
    return int(mask.sum())


def _send_pill_visible(hwnd) -> bool:
    """按住右 Alt 后检测绿色「松开发送」胶囊是否出现（录音已触发）。"""
    try:
        import numpy as np
        from . import capture as _cap
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return False
        arr = np.asarray(shot.convert("RGB"), dtype=np.int16)
        from .scale import area as _area
        from .visual_settings import value
        return _capsule_green_count(arr) > _area(value("voice_area_min"))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[语音] 胶囊检测失败: {e}")
        return False


def _pick_cable_endpoints(devices, wasapi_idx):
    """选择指定音频接口中的首对虚拟声卡端点，排除名称含 4- 的设备。"""
    out_idx = in_idx = None
    for idx, d in enumerate(devices):
        name = str(d.get("name") or "")
        if d.get("hostapi") != wasapi_idx or "4-" in name:
            continue
        if out_idx is None and "VB-Audio" in name \
                and int(d.get("max_output_channels") or 0) > 0:
            out_idx = idx
        elif in_idx is None and "CABLE Output" in name \
                and int(d.get("max_input_channels") or 0) > 0:
            in_idx = idx
    return out_idx, in_idx


# ---------- 默认录音设备切换（IPolicyConfig） ----------

_CLSID_POLICY_CONFIG = "{870af99c-171d-4f9e-af0d-e63df40c2bc9}"
_SETDEFAULT_SLOT = 13
_POLICY_IIDS = (
    "{F8679F50-850A-41CF-9C72-430F290290C8}",
    "{CA286FC3-91FD-42C3-8E9B-CAAFA66242E3}",
)


def _policy_guid(s):
    g = (ctypes.c_ulong * 4)()
    hr = ctypes.windll.ole32.IIDFromString(ctypes.c_wchar_p(s), g)
    if hr != 0:
        raise RuntimeError(f"IIDFromString 失败 0x{hr:08x}")
    return g


def _set_default_endpoint(device_id, role=0) -> bool:
    """设置默认端点；角色零、一、二分别表示控制台、多媒体和通信。"""
    from ctypes import POINTER, WINFUNCTYPE, HRESULT, c_int, c_void_p, c_wchar_p
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    for iid_s in _POLICY_IIDS:
        try:
            clsid = _policy_guid(_CLSID_POLICY_CONFIG)
            iid = _policy_guid(iid_s)
        except Exception:
            continue
        pp = c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                    ctypes.byref(iid), ctypes.byref(pp))
        if hr != 0 or not pp.value:
            continue
        vtbl_ptr = ctypes.cast(pp, POINTER(c_void_p)).contents.value
        slots = ctypes.cast(vtbl_ptr, POINTER(c_void_p * 15)).contents
        fn = WINFUNCTYPE(HRESULT, c_void_p, c_wchar_p, c_int)(slots[_SETDEFAULT_SLOT])
        hr = fn(pp, device_id, role)
        WINFUNCTYPE(HRESULT, c_void_p)(slots[2])(pp)
        if hr == 0:
            return True
    return False


def _default_capture_id(role_value):
    """当前默认录音端点 id。失败返回 None。"""
    try:
        from pycaw.pycaw import AudioUtilities, EDataFlow
        ctypes.windll.ole32.CoInitialize(None)
        enum = AudioUtilities.GetDeviceEnumerator()
        dev = enum.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, role_value)
        return dev.GetId()
    except Exception:
        return None


def _find_endpoint_id_by_name(name_sub, capture=True):
    """按名字找活动端点 id（排除带「4-」的别名声缆）。"""
    try:
        from pycaw.constants import DEVICE_STATE
        from pycaw.pycaw import AudioUtilities, EDataFlow
        ctypes.windll.ole32.CoInitialize(None)
        enum = AudioUtilities.GetDeviceEnumerator()
        flow = EDataFlow.eCapture.value if capture else EDataFlow.eRender.value
        coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE.ACTIVE.value)
        for i in range(coll.GetCount()):
            d = coll.Item(i)
            nm = AudioUtilities.CreateDevice(d).FriendlyName or ""
            if name_sub.lower() in nm.lower() and "4-" not in nm:
                return d.GetId()
    except Exception:
        return None
    return None


class _VoiceChannel:
    """VB-CABLE 语音通道：端点动态探测 + 持久渲染流 + 环回质检 + 录音设备切换。"""

    _RENDER_RATES = (48000, 44100)
    _CAPTURE_RATES = (44100, 48000)
    _GATE_ATTEMPTS = 5
    _GATE_MIN_RMS = 1e-4
    _CAPTURE_ROLES = (0, 1, 2)

    def __init__(self):
        self._stream = None
        self.render_rate = None
        self.out_idx = None
        self.in_idx = None

    def _discover(self) -> bool:
        import sounddevice as sd
        apis = sd.query_hostapis()
        wasapi = next((i for i, a in enumerate(apis)
                       if "WASAPI" in str(a.get("name") or "")), None)
        if wasapi is None:
            return False
        devices = [{"name": str(d["name"]), "hostapi": int(d["hostapi"]),
                    "max_input_channels": int(d["max_input_channels"]),
                    "max_output_channels": int(d["max_output_channels"])}
                   for d in sd.query_devices()]
        out_idx, in_idx = _pick_cable_endpoints(devices, wasapi)
        if out_idx is None or in_idx is None:
            return False
        self.out_idx, self.in_idx = out_idx, in_idx
        return True

    def ensure_stream(self) -> bool:
        """端点探测 + 持久渲染流确保已开。"""
        import sounddevice as sd
        if self._stream is not None:
            try:
                if self._stream.active:
                    return True
            except Exception:
                pass
            self._close_stream()
        if not self._discover():
            return False
        for rate in self._RENDER_RATES:
            try:
                stream = sd.OutputStream(samplerate=rate, device=self.out_idx,
                                         channels=2, dtype="float32")
                stream.start()
            except Exception:
                continue
            self._stream = stream
            self.render_rate = rate
            logger.info(f"[语音] 持久渲染流已启动（端点 {self.out_idx}，{rate}Hz）")
            return True
        logger.warning("[语音] 渲染流启动失败（VB-CABLE 播放端不可用）")
        return False

    def load_resampled(self, wav_path):
        """读 wav 并重采样到渲染流规格（float32 双声道）。"""
        import numpy as np
        import soundfile as sf
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        if data.shape[1] == 1:
            data = np.column_stack([data[:, 0], data[:, 0]])
        else:
            data = data[:, :2]
        n = int(data.shape[0] * self.render_rate / max(1, sr))
        if n <= 0:
            return None, 0.0
        out = np.column_stack([
            np.interp(np.linspace(0, data.shape[0] - 1, n),
                      np.arange(data.shape[0]), data[:, c])
            for c in (0, 1)]).astype(np.float32)
        return out, n / float(self.render_rate)

    def loopback_gate(self, data48) -> bool:
        """环回质检：写一遍音频并从录音端实采，电平达标才放行。"""
        import numpy as np
        import sounddevice as sd
        dur = data48.shape[0] / float(self.render_rate)
        for rate in self._CAPTURE_RATES:
            for _attempt in range(self._GATE_ATTEMPTS):
                try:
                    rec = sd.rec(int(rate * (dur + 0.8)), samplerate=rate,
                                 channels=2, device=self.in_idx,
                                 dtype="float32", blocking=False)
                    self._stream.write(data48)
                    time.sleep(0.8)
                    seg = rec[:, 0]
                    mx = float(np.max(np.abs(seg)))
                    rms = float(np.sqrt(np.mean(seg ** 2)))
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"[语音] 环回尝试失败（{rate}Hz）: {e}")
                    break
                if mx <= 1.0 and self._GATE_MIN_RMS < rms:
                    logger.info(f"[语音] 环回质检通过（{rate}Hz，RMS={rms:.6f}）")
                    return True
                time.sleep(0.5)
        logger.warning("[语音] 环回质检未通过，中止（不发静音）")
        return False

    def write(self, data48):
        self._stream.write(data48)

    def switch_default_capture(self):
        """三个 role 的默认录音设备切到 CABLE Output（逐一回读校验）。"""
        cable_id = _find_endpoint_id_by_name("CABLE Output", capture=True)
        if not cable_id:
            logger.warning("[语音] 未找到 CABLE Output 录音端点")
            return None
        orig = {r: _default_capture_id(r) for r in self._CAPTURE_ROLES}
        ok = all(_set_default_endpoint(cable_id, role=r) for r in self._CAPTURE_ROLES)
        now = {r: _default_capture_id(r) for r in self._CAPTURE_ROLES}
        if not ok or any(now.get(r) != cable_id for r in self._CAPTURE_ROLES):
            logger.warning("[语音] 默认录音设备切换未确认，中止（真实麦克风未动）")
            self.restore_default_capture(orig)
            return None
        return orig

    def restore_default_capture(self, orig):
        """恢复原默认录音设备（finally 必跑）。"""
        if not orig:
            return
        for r, dev_id in orig.items():
            if dev_id:
                try:
                    _set_default_endpoint(dev_id, role=r)
                except Exception:
                    pass

    def _close_stream(self):
        try:
            if self._stream is not None:
                self._stream.close()
        except Exception:
            pass
        self._stream = None


_CHANNEL = None


def _get_channel():
    """进程内语音通道单例；音频依赖缺失返回 None。"""
    global _CHANNEL
    if _CHANNEL is None:
        try:
            import numpy  # noqa: F401
            import sounddevice  # noqa: F401
            import soundfile  # noqa: F401
        except ImportError as e:
            logger.info(f"[语音] 音频依赖不可用（{e}），语音发送停用")
            _CHANNEL = False
            return None
        _CHANNEL = _VoiceChannel()
    return _CHANNEL or None


def is_available() -> bool:
    """语音发送通道是否可用（依赖齐 + VB-CABLE 端点存在）。"""
    ch = _get_channel()
    if ch is None:
        return False
    try:
        return ch._discover()
    except Exception:
        return False


# 录音启动、播放结束和松键后的固定等待时间。
_VOICE_PRE_ALT = 1.2   # 按下右 Alt 后等录音启动
_VOICE_TAIL = 0.6      # 音频写完后的尾巴（防尾字被截）
_VOICE_AFTER = 2.5     # 松开后等微信完成发送


def send_voice(hwnd, wav_path: str) -> bool:
    """校验端点、音频电平和录音提示后执行语音发送，失败时返回假。"""
    ch = _get_channel()
    if ch is None:
        return False
    if not ch.ensure_stream():
        logger.warning("[语音] VB-CABLE 端点不可用（请确认已安装 VB-CABLE 虚拟声卡）")
        return False
    try:
        data48, dur = ch.load_resampled(wav_path)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[语音] 音频读取失败: {e}")
        return False
    if data48 is None or dur <= 0:
        logger.error("[语音] 音频内容为空，中止")
        return False
    if not ch.loopback_gate(data48):
        return False
    orig = ch.switch_default_capture()
    if orig is None:
        return False
    try:
        import pyautogui
        from . import capture as _cap
        from .sender import input_focus_point
        _cap.foreground(hwnd)
        time.sleep(0.3)
        point = input_focus_point(hwnd)
        if not point:
            logger.warning("[语音] 无法定位输入框，中止")
            return False
        pyautogui.click(*point)
        time.sleep(0.5)
        if not alt_down(right=True):
            logger.warning("[语音] SendInput 右 Alt 按下失败，中止")
            return False
        time.sleep(_VOICE_PRE_ALT)
        if not _send_pill_visible(hwnd):
            alt_up(right=True)
            logger.warning("[语音] 松开发送胶囊未出现（录音未触发），中止")
            return False
        ch.write(data48)
        time.sleep(_VOICE_TAIL)
        alt_up(right=True)
        time.sleep(_VOICE_AFTER)
        logger.info(f"[语音] 已发送（{dur:.1f}s）")
        return True
    finally:
        ch.restore_default_capture(orig)
