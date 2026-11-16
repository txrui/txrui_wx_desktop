"""为桌面网页和本地 HTTP 接口提供状态查询、配置保存及运行时操作。

带安全装饰器的方法将异常转换为错误字典；启动和停止后的清理使用后台线程。
调试方法可读取截图、检测结果或执行发送，具体副作用由各方法参数决定。
"""
from __future__ import annotations

import functools
import threading

from . import state as _st
from .region_settings import get_regions as _manual_regions


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return wrapper


class TxruiBridge:
    """通过共享运行时提供页面接口，每个公开操作返回结果字典。"""

    def __init__(self, runtime):
        self.rt = runtime

    # ---------- 状态拉取（前端 1s 轮询） ----------
    @_safe
    def get_status(self) -> dict:
        snap = _st.snapshot()
        from . import config as C
        from .runtime import resolve_ws_target
        ws_url, _, target = resolve_ws_target()
        return {"ok": True, "state": snap, "events": _st.get_events(30),
                "blocked": snap.get("blocked_recent", []),
                "logs": _st.get_logs(120),
                "config": {"core_ws_url": C.CORE_WS_URL, "connector_id": C.CONNECTOR_ID,
                           "account_id": C.WECHAT_ACCOUNT_ID, "poll_sec": C.POLL_SEC,
                           "has_token": bool(C.CONNECTOR_TOKEN),
                           "token": C.CONNECTOR_TOKEN,
                           "filter_extra": C.FILTER_EXTRA, "filter_allow": C.FILTER_ALLOW,
                           "astrbot_enabled": C.ASTRBOT_ENABLED == "1",
                           "astrbot_ws_url": C.ASTRBOT_WS_URL,
                           "astrbot_token": C.ASTRBOT_TOKEN,
                           "has_astrbot_token": bool(C.ASTRBOT_TOKEN),
                           "backend_target": target,
                           "effective_ws_url": ws_url}}

    @_safe
    def get_config(self) -> dict:
        from . import config as C
        from .runtime import resolve_ws_target
        ws_url, _, target = resolve_ws_target()
        return {"ok": True, "config": {"core_ws_url": C.CORE_WS_URL,
                                      "connector_id": C.CONNECTOR_ID,
                                      "account_id": C.WECHAT_ACCOUNT_ID,
                                      "poll_sec": C.POLL_SEC,
                                      "has_token": bool(C.CONNECTOR_TOKEN),
                                      "token": C.CONNECTOR_TOKEN,
                                      "filter_extra": C.FILTER_EXTRA,
                                      "filter_allow": C.FILTER_ALLOW,
                                      "astrbot_enabled": C.ASTRBOT_ENABLED == "1",
                                      "astrbot_ws_url": C.ASTRBOT_WS_URL,
                                      "astrbot_token": C.ASTRBOT_TOKEN,
                                      "has_astrbot_token": bool(C.ASTRBOT_TOKEN),
                                      "backend_target": target,
                                      "effective_ws_url": ws_url}}

    @_safe
    def save_config(self, patch: dict) -> dict:
        """保存允许的配置键并刷新内存值；现有网络客户端需重启采集后更新。"""
        if not isinstance(patch, dict):
            return {"ok": False, "error": "patch 必须是对象"}
        from . import config as C
        try:
            applied = C.save_patch(patch)
        except OSError as e:
            return {"ok": False, "error": f"写 config.toml 失败: {e}"}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        _st.log(f"配置已保存: {','.join(applied)}（重启采集生效）")
        return {"ok": True, "applied": applied}

    # ---------- 运行时动作 ----------
    @_safe
    def runtime_start(self) -> dict:
        if _st.snapshot().get("running"):
            return {"ok": True, "msg": "已在运行"}
        from . import config as C
        from .runtime import resolve_ws_target
        _, ws_token, target = resolve_ws_target()
        if not ws_token:
            if target == "astrbot":
                return {"ok": False, "error": "缺少 ASTRBOT_TOKEN：先在设置页填入与 AstrBot 插件一致的令牌"}
            return {"ok": False, "error": "缺少 CONNECTOR_TOKEN，先在设置页填入 core 签发的令牌"}
        threading.Thread(target=self._start_bg, daemon=True).start()
        return {"ok": True, "msg": "启动中…"}

    def _start_bg(self):
        try:
            _st.log("网页控制台：启动采集中…")
            self.rt.start()
        except Exception as e:  # noqa: BLE001
            _st.set_field("last_error", str(e)[:300])
            _st.log(f"启动失败: {e}")

    @_safe
    def runtime_stop(self) -> dict:
        self.rt.stop()
        # 等待运行线程退出后重建停止标记和线程引用，便于再次启动。
        import threading as _th

        def _reset():
            try:
                if self.rt.thread is not None:
                    self.rt.thread.join(timeout=5)
            except Exception:
                pass
            from threading import Event
            self.rt.stop_event = Event()
            self.rt.loop = None
            self.rt.thread = None
            _st.set_field("backend_ok", False)
        _th.Thread(target=_reset, daemon=True).start()
        _st.log("网页控制台：已请求停止")
        return {"ok": True}

    @_safe
    def test_shot(self) -> dict:
        r = self.rt.test_shot()
        return {"ok": True, "result": r}

    @_safe
    def test_send(self, chat: str = "", text: str = "") -> dict:
        """过滤目标并切换会话后，直接发送指定文本或默认时间戳探针。

        使用文本发送工具，不经过网络下行分派，也不执行下行类型复验。
        """
        text = (text or "").strip() or f"txrui探针 {__import__('time').strftime('%H:%M:%S')}（收到请勿回）"
        chat = (chat or "").strip()
        from . import config as C
        if not chat:
            return {"ok": False, "error": "请填写目标会话名（微信列表里看到的名字）"}
        backend = getattr(self.rt, "backend", None)
        if backend is None or getattr(backend, "_hwnd", None) is None:
            return {"ok": False, "error": "后端未连接：先点“启动采集”"}
        from .filters import is_blocked
        blocked, reason = is_blocked(chat)
        if blocked:
            return {"ok": False, "error": f"目标被过滤拦截: {reason}"}
        try:
            if not backend.ensure_chat(chat):
                return {"ok": False, "error": f"切不到会话 {chat!r}（列表找不到/标题复验不过）"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"切换异常: {e}"}
        from . import sender as _sender
        try:
            ok = _sender.send_text(backend._hwnd, chat, text)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"发送异常: {e}"}
        _st.bump("sent_ok" if ok else "sent_fail")
        _st.log(f"[自检发送] →{chat!r} {'成功' if ok else '失败'}: {text[:40]}")
        if ok:
            return {"ok": True, "result": f"已发送到 {chat!r}：{text[:60]}"}
        return {"ok": False, "error": "visual_send_failed（输入框定位/粘贴失败，看截图识别页确认三区域）"}

    @_safe
    def read_title(self) -> dict:
        r = self.rt.read_title_now()
        return {"ok": True, "result": r}

    @_safe
    def get_capabilities(self) -> dict:
        """检查剪贴板依赖、虚拟声卡、转写配置和接收目录，不发送消息。

        同时返回当前网络客户端的能力声明；转写地址仅检查是否已配置。
        """
        from . import config as C
        items = []

        # 1) 剪贴板文件能力
        try:
            import win32clipboard  # noqa: F401
            import win32con  # noqa: F401
            items.append({"key": "clipboard_file", "label": "剪贴板文件（发图片/文件/表情）",
                          "ok": True, "detail": "pywin32 可用"})
        except ImportError as e:
            items.append({"key": "clipboard_file", "label": "剪贴板文件（发图片/文件/表情）",
                          "ok": False, "detail": f"缺 pywin32（{e}）→ 媒体发送不可用"})

        # 2) VB-CABLE 语音通道
        try:
            from . import voice_send as _vs
            if _vs.is_available():
                items.append({"key": "voice_channel", "label": "VB-CABLE 语音通道（发真语音）",
                              "ok": True, "detail": "端点已就绪"})
            else:
                items.append({"key": "voice_channel", "label": "VB-CABLE 语音通道（发真语音）",
                              "ok": False,
                              "detail": "未检测到 VB-CABLE/音频依赖 → 语音降级为文件发送"})
        except Exception as e:  # noqa: BLE001
            items.append({"key": "voice_channel", "label": "VB-CABLE 语音通道（发真语音）",
                          "ok": False, "detail": f"探测失败: {e}"})

        # 3) ASR 端点
        ep = str(C.ASR_ENDPOINT or "").strip()
        items.append({"key": "asr", "label": "ASR 语音转写端点",
                      "ok": bool(ep),
                      "detail": ep if ep else "未配置（语音只上报微信自动转文字文本）"})

        # 4) 微信接收文件目录
        from . import media_grab as _mg
        dirs = _mg._file_dirs()
        items.append({"key": "file_dirs", "label": "微信接收文件目录（收文件本体）",
                      "ok": bool(dirs),
                      "detail": "; ".join(dirs) if dirs else "未找到（文件只能收文件名占位）"})

        # 5) 上报给 core 的能力声明
        caps = {}
        try:
            client = getattr(self.rt, "client", None)
            caps = dict(getattr(client, "capabilities", {}) or {})
        except Exception:
            caps = {}
        return {"ok": True, "capabilities": caps, "items": items}

    @_safe
    def test_media(self) -> dict:
        """识别当前消息区媒体并按类型计数，返回前三十个气泡，不发送消息。"""
        from . import capture as _cap
        from . import media as _media
        from . import ocr as _ocr
        from . import scale as _scale

        hwnd = None
        backend = getattr(self.rt, "backend", None)
        if backend is not None and getattr(backend, "_hwnd", None):
            hwnd = backend._hwnd
        if not hwnd:
            hwnd = _cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口"}
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "截图失败"}
        w, h = shot.size
        mr = getattr(backend, "_message_region", None) if backend else None
        if mr is None:
            from . import regions as _rg
            mr = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)[1]
        region = shot.crop((int(w * mr[0]), int(h * mr[1]),
                             int(w * mr[2]), int(h * mr[3])))
        items = _ocr.ocr_image(region)
        bubbles = _media.detect_media_bubbles(region, items, _scale.active_scale())
        counts: dict[str, int] = {}
        for b in bubbles:
            k = str(b.get("kind", "?"))
            counts[k] = counts.get(k, 0) + 1
        _st.log(f"[媒体自检] 检出 {len(bubbles)} 个气泡: {counts}")
        return {"ok": True, "count": len(bubbles), "counts": counts,
                "bubbles": [{"kind": b.get("kind"), "x": b.get("x"), "y": b.get("y"),
                             "w": b.get("w"), "h": b.get("h"),
                             "text": (b.get("text") or "")[:60]} for b in bubbles[:30]]}

    @_safe
    def test_connection(self, cfg: dict | None = None) -> dict:
        """建立独立探测连接，以握手确认帧验证配置并返回往返耗时。

        表单非空值覆盖当前连接配置；收到非预期帧或超时返回失败。
        """
        import asyncio
        import json as _json
        import time as _time

        from . import config as C
        from .runtime import resolve_ws_target
        cfg = cfg if isinstance(cfg, dict) else {}
        default_url, default_token, target = resolve_ws_target()
        ws_url = str(cfg.get("ws_url") or cfg.get("core_ws_url")
                      or cfg.get("CORE_WS_URL") or default_url).strip()
        cid = str(cfg.get("connector_id") or cfg.get("CONNECTOR_ID")
                  or cfg.get("connector_id_", "") or C.CONNECTOR_ID).strip()
        # 前端表单留空 token 时回退已保存配置，避免“免保存验证”误报缺 token
        token = str(cfg.get("token") or cfg.get("CONNECTOR_TOKEN")
                    or cfg.get("ASTRBOT_TOKEN") or default_token or C.CONNECTOR_TOKEN)
        account = str(cfg.get("account_id") or cfg.get("WECHAT_ACCOUNT_ID")
                      or C.WECHAT_ACCOUNT_ID).strip()
        if not ws_url:
            return {"ok": False, "error": "缺少 WS 地址"}
        if not cid:
            return {"ok": False, "error": "缺少 CONNECTOR_ID"}
        if not token:
            return {"ok": False, "error": "缺少连接令牌（服务端签发后填入再验证）"}

        async def _probe():
            import websockets
            t0 = _time.time()
            async with websockets.connect(ws_url, max_size=1 * 1024 * 1024) as ws:
                await ws.send(_json.dumps(
                    {"type": "hello", "connector_id": cid, "token": token,
                     "protocol_version": "1.0", "account_ids": account,
                     "client_info": "txrui_desktop/verify", "probe": True,
                     "capabilities": {"text": True}}, ensure_ascii=False))
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
                ack = _json.loads(raw)
                if ack.get("type") != "hello_ack":
                    raise RuntimeError(f"握手被拒: {str(ack)[:200]}")
                ms = int((_time.time() - t0) * 1000)
                return ms

        try:
            ms = asyncio.run(asyncio.wait_for(_probe(), timeout=12))
        except (ConnectionRefusedError, OSError) as e:
            return {"ok": False, "error": f"连不上服务端（地址/端口错？）: {e}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "连接超时（12s 无 hello_ack，检查服务端是否启动）"}
        return {"ok": True, "result": f"hello_ack {ms}ms（{cid} 鉴权通过）"}

    @_safe
    def ocr_preview(self, max_blocks: int = 200) -> dict:
        """识别整窗文字，返回限宽预览图和按同一比例换算的文本框。"""
        import base64
        import io
        import time as _time

        from . import capture as _cap
        from . import ocr as _ocr
        t0 = _time.time()
        hwnd = None
        try:
            if self.rt is not None and getattr(self.rt, "backend", None) is not None \
                    and getattr(self.rt.backend, "_hwnd", None):
                hwnd = self.rt.backend._hwnd
        except Exception:
            hwnd = None
        if not hwnd:
            hwnd = _cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口（请确认微信已登录）"}
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "PrintWindow 截图失败（窗口被最小化？还原后再试）"}
        ow, oh = shot.size
        items = _ocr.ocr_image(shot)
        if not items:
            # 初始化失败时单独返回引擎不可用信息，区分未识别到文字的情况。
            if _ocr.get_engine() is None:
                return {"ok": False, "error": "OCR 引擎不可用（pip install rapidocr-onnxruntime 后重试）"}
        # 预览图限宽 960，坐标同步缩放，前端 canvas 可直接套用
        disp_w = 960 if ow > 960 else ow
        scale = disp_w / ow if ow else 1.0
        disp_h = int(oh * scale)
        try:
            small = shot.convert("RGB").resize((disp_w, disp_h))
            buf = io.BytesIO()
            small.save(buf, "JPEG", quality=72)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            buf = io.BytesIO()
            shot.convert("RGB").save(buf, "PNG")
            uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
            scale = 1.0
            disp_w, disp_h = ow, oh
        out = []
        for it in (items or [])[:max(1, int(max_blocks or 200))]:
            out.append({"text": it.get("text", ""),
                        "x": int(it.get("x", 0) * scale), "y": int(it.get("y", 0) * scale),
                        "w": int(it.get("w", 0) * scale), "h": int(it.get("h", 0) * scale)})
        ms = int((_time.time() - t0) * 1000)
        _st.log(f"OCR 预览 hwnd=0x{hwnd:x} {ow}x{oh}→{disp_w}x{disp_h} {len(out)}块 {ms}ms")
        return {"ok": True, "image": uri, "width": disp_w, "height": disp_h,
                "orig_width": ow, "orig_height": oh, "count": len(out),
                "items": out, "elapsed_ms": ms}

    # ---------- 调试页（全方位自测识别链路） ----------
    @_safe
    def debug_env(self) -> dict:
        """汇总依赖、微信窗口、显示缩放、区域探测、识别引擎及连接目标信息。"""
        import importlib
        import os

        from . import capture as _cap
        from . import config as C
        from . import ocr as _ocr
        from . import regions as _rg
        from . import scale as _scale

        # 1) Python 依赖
        deps = []
        for mod, label, why in (
            ("PIL", "Pillow", "截图/裁剪"),
            ("numpy", "NumPy", "像素判据"),
            ("rapidocr", "RapidOCR", "文字识别"),
            ("win32clipboard", "pywin32", "剪贴板文件/图片"),
            ("pyautogui", "pyautogui", "点击会话/发送"),
            ("websockets", "websockets", "WS 连接"),
        ):
            try:
                m = importlib.import_module(mod)
                ver = getattr(m, "__version__", "") or ""
                deps.append({"key": mod, "label": label, "why": why, "ok": True,
                             "detail": ver or "已安装"})
            except Exception as e:  # noqa: BLE001
                deps.append({"key": mod, "label": label, "why": why, "ok": False,
                             "detail": f"缺 {type(e).__name__}"})
        # 2) 微信窗口
        hwnd = None
        win_err = ""
        try:
            hwnd = _cap.find_wechat_window()
        except Exception as e:  # noqa: BLE001
            win_err = str(e)
        win_info = {"hwnd": hwnd, "title": "", "rect": None, "ok": bool(hwnd),
                    "error": win_err}
        if hwnd:
            try:
                win_info["title"] = _cap.window_title(hwnd)
                win_info["rect"] = list(_cap.window_rect(hwnd) or [])
            except Exception:
                pass
        # 3) 缩放档位
        scale_pct = _scale.active_scale()
        try:
            measured = _cap.monitor_dpi_scale(hwnd) if hwnd else 0
        except Exception:
            measured = 0
        # 4) 三区域（运行时像素探测 + 静态标定兜底）
        regions = []
        detect = {"divider_x": None, "header_y": None, "input_top_y": None,
                  "mode": "static"}
        try:
            size = _cap.window_rect(hwnd)[2:] if hwnd else _rg.WINDOW_SIZE
            shot = None
            if hwnd:
                shot = _cap.capture_window(hwnd)
            if shot is not None:
                detect["divider_x"] = _rg.detect_divider_x(shot)
                if detect["divider_x"]:
                    detect["header_y"] = _rg.detect_header_y(
                        shot, detect["divider_x"] + 10, size[0] - 20, _scale.active_scale())
                    detect["input_top_y"] = _rg.detect_input_top_y(
                        shot, detect["divider_x"] + 10, size[0] - 20)
                detect["mode"] = "pixel" if detect["divider_x"] else "static"
            if _manual_regions():
                detect["mode"] = "manual"
            rs = _rg.regions_for_window(size[0], size[1], scale_pct, shot=shot)
            names = ("会话区", "消息区", "标题区")
            keys = ("session", "message", "title")
            for nm, k, r in zip(names, keys, rs):
                regions.append({"key": k, "label": nm,
                                "ratio": [round(v, 4) for v in r],
                                "px": [int(size[0] * r[0]), int(size[1] * r[1]),
                                       int(size[0] * r[2]), int(size[1] * r[3])]})
            win_size = list(size)
        except Exception as e:  # noqa: BLE001
            win_size = list(_rg.WINDOW_SIZE)
            regions = []
        # 5) OCR 引擎
        t0 = __import__("time").time()
        engine = _ocr.get_engine()
        engine_ms = int((__import__("time").time() - t0) * 1000)
        # 6) 配置文件
        cfg_path = C.CONFIG_PATH
        cfg_exists = bool(cfg_path and os.path.isfile(cfg_path))
        # 7) 连接目标
        from .runtime import resolve_ws_target
        ws_url, ws_token, target = resolve_ws_target()
        return {"ok": True, "deps": deps, "window": win_info,
                "scale": {"active": scale_pct, "measured": measured,
                          "calib": _scale.CALIB_SCALE, "k": round(_scale.k(), 4),
                          "min": _scale.MIN_SCALE, "max": _scale.MAX_SCALE,
                          "out_of_range": _scale.out_of_range()},
                "regions": regions, "window_size": win_size,
                "detect": detect,
                "ocr_engine": {"ok": engine is not None,
                               "detail": "RapidOCR PP-OCRV5 mobile 已加载" if engine
                                         else "不可用（pip install rapidocr-onnxruntime）",
                               "load_ms": engine_ms},
                "config": {"path": cfg_path, "exists": cfg_exists},
                "target": {"name": target, "ws_url": ws_url,
                           "has_token": bool(ws_token)}}

    @_safe
    def debug_scale(self, pct: int = 0, apply: bool = True) -> dict:
        """查询或设置生效缩放，返回区域像素框及带框预览图。

        pct 非零时立即写入共享缩放状态；apply 参数当前未参与控制。
        """
        import base64
        import io

        from . import capture as _cap
        from . import regions as _rg
        from . import scale as _scale

        lo, hi = _scale.supported()
        hwnd = None
        backend = getattr(self.rt, "backend", None)
        if backend is not None and getattr(backend, "_hwnd", None):
            hwnd = backend._hwnd
        if not hwnd:
            hwnd = _cap.find_wechat_window()

        # 1) 设置档位（pct=0 表示只查）
        applied = _scale.active_scale()
        changed = False
        if pct:
            applied = _scale.set_active_scale(int(pct))
            changed = True
        out_of_range = _scale.out_of_range()
        measured = 0
        try:
            measured = _cap.monitor_dpi_scale(hwnd) if hwnd else 0
        except Exception:
            measured = 0

        # 2) 三区域像素框（带运行时探测）
        size = _rg.WINDOW_SIZE
        regions = []
        detect = {"divider_x": None, "header_y": None, "input_top_y": None,
                  "mode": "static"}
        shot = None
        try:
            if hwnd:
                wr = _cap.window_rect(hwnd)
                if wr:
                    size = (wr[2], wr[3])
                shot = _cap.capture_window(hwnd)
            if shot is not None:
                detect["divider_x"] = _rg.detect_divider_x(shot)
                if detect["divider_x"]:
                    detect["header_y"] = _rg.detect_header_y(
                        shot, detect["divider_x"] + 10, size[0] - 20, _scale.active_scale())
                    detect["input_top_y"] = _rg.detect_input_top_y(
                        shot, detect["divider_x"] + 10, size[0] - 20)
                detect["mode"] = "pixel" if detect["divider_x"] else "static"
            if _manual_regions():
                detect["mode"] = "manual"
            rs = _rg.regions_for_window(size[0], size[1], applied, shot=shot)
            names = (("会话区", "session"), ("消息区", "message"), ("标题区", "title"))
            for (nm, key), r in zip(names, rs):
                regions.append({"key": key, "label": nm,
                                "ratio": [round(v, 4) for v in r],
                                "px": [int(size[0] * r[0]), int(size[1] * r[1]),
                                       int(size[0] * r[2]), int(size[1] * r[3])]})
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"区域计算失败: {e}"}

        # 3) 预览图：整窗 + 三个区域框
        image = ""
        disp = None
        if shot is not None:
            try:
                ow, oh = shot.size
                disp_w = min(960, ow)
                sc = disp_w / ow if ow else 1.0
                disp_h = max(1, int(oh * sc))
                from PIL import Image, ImageDraw
                small = shot.convert("RGB").resize((disp_w, disp_h), Image.LANCZOS)
                dr = ImageDraw.Draw(small)
                colors = {"session": "#22c55e", "message": "#38bdf8", "title": "#f59e0b"}
                for g in regions:
                    x0 = int(g["px"][0] * sc)
                    y0 = int(g["px"][1] * sc)
                    x1 = int(g["px"][2] * sc)
                    y1 = int(g["px"][3] * sc)
                    dr.rectangle([x0, y0, x1, y1], outline=colors.get(g["key"], "#e2e8f0"),
                                     width=2)
                    dr.text((x0 + 3, max(0, y0 - 12)), g["label"],
                                fill=colors.get(g["key"], "#e2e8f0"))
                buf = io.BytesIO()
                small.save(buf, "JPEG", quality=78)
                image = ("data:image/jpeg;base64," +
                         base64.b64encode(buf.getvalue()).decode("ascii"))
                disp = [disp_w, disp_h]
            except Exception as e:  # noqa: BLE001
                image = ""
        return {"ok": True, "active": applied, "changed": changed,
                "measured": measured, "out_of_range": out_of_range,
                "min": lo, "max": hi, "calib": _scale.CALIB_SCALE,
                "k": round(_scale.k(), 4),
                "window_size": list(size), "regions": regions,
                "detect": detect,
                "image": image, "display": disp}

    @_safe
    def debug_regions(self, action: str = "preview", regions=None, window_size=None,
                      visual=None, manual_primary: bool = True) -> dict:
        """预览、保存或清除比例标定，保存时校验窗口尺寸、区域和视觉参数。"""
        import base64
        import io
        from . import capture as cap, regions as rg, region_settings as settings

        if action not in ("preview", "save", "reset"):
            raise ValueError("未知区域编辑动作")
        backend = getattr(self.rt, "backend", None)
        hwnd = getattr(backend, "_hwnd", None) or cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口"}
        shot = cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "截图失败，请还原微信窗口"}
        w, h = shot.size
        if action == "save":
            if window_size != [w, h]:
                raise ValueError("微信窗口尺寸已变化，请刷新预览后重新调整")
            checked = settings.validate(regions)
            if any((box[2] - box[0]) * w < 8 or (box[3] - box[1]) * h < 8
                   for box in checked.values()):
                raise ValueError("每个区域的宽高至少为 8 像素")
            from . import visual_settings as vs
            if visual is None:
                settings.save_regions(checked)
            else:
                checked_visual = vs.validate(visual)
                for key, box in checked_visual.items():
                    if vs.SCHEMA[key]["type"] == "rect" and (
                            (box[2]-box[0])*w < 8 or (box[3]-box[1])*h < 8):
                        raise ValueError("区域宽高至少为 8 像素")
                if checked_visual.get("send_mode") == "click" and "send_button" not in checked_visual:
                    raise ValueError("点击发送模式需要先标定发送按钮位置")
                settings.save_profile(checked if manual_primary else {}, checked_visual)
        elif action == "reset":
            settings.reset_regions()
        boxes = rg.regions_for_window(w, h, shot=shot)
        # 全部调用共享 regions_for_window；后续采集与调试截图使用相同边界。
        if backend is not None and hasattr(backend, "_apply_regions"):
            backend._apply_regions(shot.size, shot=shot)
        small = shot.convert("RGB")
        buf = io.BytesIO()
        small.save(buf, "PNG")  # 无损原始像素供前端取色，避免 JPEG 引入色偏
        from . import visual_settings as vs
        return {"ok": True, "manual": bool(settings.get_regions()),
                "visual": settings.get_visual(), "schema": list(vs.SCHEMA.values()),
                "effective": vs.effective(w, h, boxes),
                "defaults": vs.effective(w, h, boxes, use_overrides=False),
                "auto_regions": dict(zip(("session", "message", "title"),
                                         rg.regions_for_window(w, h, shot=shot, use_manual=False))),
                "window_size": [w, h], "display": [w, h],
                "regions": dict(zip(("session", "message", "title"), boxes)),
                "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}

    @_safe
    def debug_shot(self, region: str = "", max_w: int = 960) -> dict:
        """返回整窗或指定主区域的缩放截图、原始尺寸与整窗裁剪框。"""
        import base64
        import io

        from . import capture as _cap
        from . import regions as _rg
        from . import scale as _scale

        hwnd = None
        backend = getattr(self.rt, "backend", None)
        if backend is not None and getattr(backend, "_hwnd", None):
            hwnd = backend._hwnd
        if not hwnd:
            hwnd = _cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口（请确认微信已登录）"}
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "PrintWindow 截图失败（窗口被最小化？还原后再试）"}
        w, h = shot.size
        region = str(region or "").strip().lower()
        box = None
        label = "整窗"
        if region in ("session", "message", "title"):
            rs = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)
            idx = {"session": 0, "message": 1, "title": 2}[region]
            r = rs[idx]
            box = (int(w * r[0]), int(h * r[1]), int(w * r[2]), int(h * r[3]))
            label = {"session": "会话区", "message": "消息区", "title": "标题区"}[region]
        crop = shot.crop(box) if box else shot
        ow, oh = crop.size
        disp_w = min(int(max_w or 960), ow)
        scale = disp_w / ow if ow else 1.0
        disp_h = max(1, int(oh * scale))
        try:
            from PIL import Image
            small = crop.convert("RGB").resize((disp_w, disp_h), Image.LANCZOS)
            buf = io.BytesIO()
            small.save(buf, "JPEG", quality=75)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            buf = io.BytesIO()
            crop.convert("RGB").save(buf, "PNG")
            uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
            scale = 1.0
            disp_w, disp_h = ow, oh
        return {"ok": True, "image": uri, "label": label, "region": region,
                "width": disp_w, "height": disp_h,
                "orig_width": ow, "orig_height": oh,
                "box": list(box) if box else [0, 0, w, h],
                "window_size": [w, h], "scale": scale}

    @_safe
    def debug_ocr(self, region: str = "", max_w: int = 960) -> dict:
        """识别整窗或指定主区域，返回预览图、缩放文本框、灰度统计和会话类型。"""
        import base64
        import io
        import time as _time

        from . import capture as _cap
        from . import ocr as _ocr
        from . import regions as _rg
        from . import scale as _scale

        hwnd = None
        backend = getattr(self.rt, "backend", None)
        if backend is not None and getattr(backend, "_hwnd", None):
            hwnd = backend._hwnd
        if not hwnd:
            hwnd = _cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口"}
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "截图失败"}
        w, h = shot.size
        region = str(region or "").strip().lower()
        box = None
        label = "整窗"
        if region in ("session", "message", "title"):
            rs = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)
            idx = {"session": 0, "message": 1, "title": 2}[region]
            r = rs[idx]
            box = (int(w * r[0]), int(h * r[1]), int(w * r[2]), int(h * r[3]))
            label = {"session": "会话区", "message": "消息区", "title": "标题区"}[region]
        crop = shot.crop(box) if box else shot
        ow, oh = crop.size
        t0 = _time.time()
        items = _ocr.ocr_image(crop)
        ms = int((_time.time() - t0) * 1000)
        # 预览图（坐标同步缩放）
        disp_w = min(int(max_w or 960), ow)
        scale = disp_w / ow if ow else 1.0
        disp_h = max(1, int(oh * scale))
        try:
            from PIL import Image
            small = crop.convert("RGB").resize((disp_w, disp_h), Image.LANCZOS)
            buf = io.BytesIO()
            small.save(buf, "JPEG", quality=75)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            buf = io.BytesIO()
            crop.convert("RGB").save(buf, "PNG")
            uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
            scale = 1.0
            disp_w, disp_h = ow, oh
        out = [{"text": it.get("text", ""),
                "x": int(it.get("x", 0) * scale), "y": int(it.get("y", 0) * scale),
                "w": int(it.get("w", 0) * scale), "h": int(it.get("h", 0) * scale)}
               for it in (items or [])[:500]]
        # 统计裁图灰度范围，辅助识别黑图和亮度异常。
        stats = {}
        try:
            import numpy as _np
            a = _np.asarray(crop.convert("L"))
            stats = {"mean": round(float(a.mean()), 1), "max": int(a.max()),
                     "min": int(a.min()), "black": bool(int(a.max()) < 10)}
        except Exception:
            pass
        _st.log(f"[调试OCR] {label} {ow}x{oh} 检出{len(out)}块 {ms}ms")
        # 同时提供会话类型摘要；缺少缓存标题时补充识别。
        chat_type = ""
        chat_type_label = ""
        chat_type_reason = ""
        member_count = None
        try:
            raw_title = getattr(backend, "_current_title", None)
            if not raw_title:
                # backend 没记录过标题 → 现读一次（只读标题区，开销小）
                if backend is not None and getattr(backend, "_hwnd", None):
                    raw_title = backend.read_title(foreground=False)
                if not raw_title:
                    # 退而求其次：用标题区裁图 OCR 一次
                    tr = _rg.regions_for_window(w, h, _scale.active_scale(),
                                                shot=shot)[2]
                    t_crop = shot.crop((int(w * tr[0]), int(h * tr[1]),
                                        int(w * tr[2]), int(h * tr[3])))
                    t_its = _ocr.ocr_image(t_crop)
                    raw_title = "".join(
                        it["text"] for it in sorted(t_its, key=lambda i: i["x"])
                        if len(it["text"].strip()) >= 2) or ""
            name_, is_g, cnt_ = _rg.parse_title(raw_title or "")
            det = _rg.detect_chat_type(raw_title or "", is_group=is_g,
                                       member_count=cnt_)
            chat_type = det.get("chat_type") or ""
            chat_type_label = _rg.chat_type_label(chat_type)
            chat_type_reason = det.get("reason", "")
            member_count = det.get("member_count")
        except Exception:
            pass
        return {"ok": True, "label": label, "region": region, "image": uri,
                "width": disp_w, "height": disp_h, "orig_width": ow, "orig_height": oh,
                "count": len(out), "items": out, "elapsed_ms": ms,
                "engine": _ocr.get_engine() is not None, "stats": stats,
                "chat_type": chat_type, "chat_type_label": chat_type_label,
                "chat_type_reason": chat_type_reason, "member_count": member_count,
                "box": list(box) if box else [0, 0, w, h]}

    @_safe
    def debug_media(self, kind: str = "all", region: str = "message") -> dict:
        """按指定区域和类型检测媒体，返回全部检测字段及带框预览。

        气泡坐标相对原始裁图，预览图单独缩放到最大宽度。
        """
        if not isinstance(kind, str) or kind not in ("all", "emoji", "image", "video", "file", "audio"):
            return {"ok": False, "error": "未知媒体类型：支持 all/emoji/image/video/file/audio"}
        if not isinstance(region, str) or region not in ("", "session", "message", "title"):
            return {"ok": False, "error": "未知目标区域：支持整窗（空字符串）/session/message/title"}
        import base64
        import io

        from . import capture as _cap
        from . import media as _media
        from . import ocr as _ocr
        from . import regions as _rg
        from . import scale as _scale

        hwnd = None
        backend = getattr(self.rt, "backend", None)
        if backend is not None and getattr(backend, "_hwnd", None):
            hwnd = backend._hwnd
        if not hwnd:
            hwnd = _cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口"}
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "截图失败"}
        w, h = shot.size
        box = (0, 0, w, h)
        label = "整窗"
        if region:
            rs = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)
            r = rs[{"session": 0, "message": 1, "title": 2}[region]]
            box = (int(w * r[0]), int(h * r[1]), int(w * r[2]), int(h * r[3]))
            label = {"session": "会话区", "message": "消息区", "title": "标题区"}[region]
        crop = shot.crop(box)
        rw, rh = crop.size
        items = _ocr.ocr_image(crop)
        detected = _media.detect_media_bubbles(crop, items, _scale.active_scale())
        bubbles = [dict(b) for b in detected if kind == "all" or b.get("kind") == kind]
        counts: dict[str, int] = {}
        for b in bubbles:
            k = str(b.get("kind", "?"))
            counts[k] = counts.get(k, 0) + 1
        # 预览图（限宽 960）+ 画框
        disp_w = min(960, rw)
        scale = disp_w / rw if rw else 1.0
        disp_h = max(1, int(rh * scale))
        try:
            from PIL import Image, ImageDraw
            small = crop.convert("RGB").resize((disp_w, disp_h), Image.LANCZOS)
            dr = ImageDraw.Draw(small)
            colors = {"image": "#22c55e", "file": "#f59e0b", "video": "#ef4444",
                      "emoji": "#a855f7", "audio": "#38bdf8"}
            for b in bubbles:
                x0 = int(b.get("x", 0) * scale)
                y0 = int(b.get("y", 0) * scale)
                x1 = x0 + max(2, int(b.get("w", 0) * scale))
                y1 = y0 + max(2, int(b.get("h", 0) * scale))
                c = colors.get(str(b.get("kind")), "#e2e8f0")
                dr.rectangle([x0, y0, x1, y1], outline=c, width=2)
                dr.text((x0 + 2, max(0, y0 - 11)), str(b.get("kind", "")), fill=c)
            buf = io.BytesIO()
            small.save(buf, "JPEG", quality=75)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"预览图生成失败: {e}"}
        _st.log(f"[调试媒体] 检出 {len(bubbles)} 个气泡: {counts}")
        return {"ok": True, "image": uri, "width": disp_w, "height": disp_h,
                "kind": kind, "region": region, "label": label,
                "orig_width": rw, "orig_height": rh, "box": list(box),
                "window_size": [w, h], "scale": scale,
                "count": len(bubbles), "counts": counts, "bubbles": bubbles}

    @_safe
    def debug_badges(self) -> dict:
        """返回未读检测区域的红点框和预览图；阈值字段展示模块常量。"""
        import base64
        import io

        from . import badge as _badge
        from . import capture as _cap
        from . import regions as _rg
        from . import scale as _scale

        hwnd = None
        backend = getattr(self.rt, "backend", None)
        if backend is not None and getattr(backend, "_hwnd", None):
            hwnd = backend._hwnd
        if not hwnd:
            hwnd = _cap.find_wechat_window()
        if not hwnd:
            return {"ok": False, "error": "未找到微信窗口"}
        shot = _cap.capture_window(hwnd)
        if shot is None:
            return {"ok": False, "error": "截图失败"}
        w, h = shot.size
        sr = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)[0]
        from .visual_settings import overrides
        sr = overrides().get("unread", sr)
        box = (int(w * sr[0]), int(h * sr[1]), int(w * sr[2]), int(h * sr[3]))
        crop = shot.crop(box)
        cw, ch = crop.size
        clusters = _badge.detect_red_clusters(shot, region=sr)
        # 预览图 + 框（clusters 是整窗坐标，换算到 crop 内）
        disp_w = min(960, cw)
        scale = disp_w / cw if cw else 1.0
        disp_h = max(1, int(ch * scale))
        try:
            from PIL import Image, ImageDraw
            small = crop.convert("RGB").resize((disp_w, disp_h), Image.LANCZOS)
            dr = ImageDraw.Draw(small)
            for (bl, bt, br, bb) in clusters:
                x0 = int((bl - box[0]) * scale)
                y0 = int((bt - box[1]) * scale)
                x1 = int((br - box[0]) * scale)
                y1 = int((bb - box[1]) * scale)
                dr.rectangle([x0, y0, x1, y1], outline="#ef4444", width=2)
            buf = io.BytesIO()
            small.save(buf, "JPEG", quality=75)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"预览图生成失败: {e}"}
        return {"ok": True, "image": uri, "width": disp_w, "height": disp_h,
                "count": len(clusters),
                "badges": [{"l": b[0], "t": b[1], "r": b[2], "b": b[3]}
                           for b in clusters[:60]],
                "thresholds": {"red": list(_badge._BADGE_RED), "tol": _badge._BADGE_TOL,
                               "area_min": _badge._BADGE_AREA_MIN,
                               "area_max": _badge._BADGE_AREA_MAX}}

    @_safe
    def debug_title(self) -> dict:
        """识别并解析当前标题，返回原文、会话名、人数和类型判定依据。"""
        from . import regions as _rg

        backend = getattr(self.rt, "backend", None)
        raw = None
        err = ""
        try:
            if backend is not None and getattr(backend, "_hwnd", None):
                raw = backend.read_title(foreground=True)
            else:
                from . import capture as _cap
                hwnd = _cap.find_wechat_window()
                if hwnd:
                    shot = _cap.capture_window(hwnd)
                    if shot:
                        from . import scale as _scale
                        w, h = shot.size
                        tr = _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)[2]
                        crop = shot.crop((int(w * tr[0]), int(h * tr[1]),
                                           int(w * tr[2]), int(h * tr[3])))
                        from . import ocr as _ocr
                        its = _ocr.ocr_image(crop)
                        texts = [it["text"] for it in sorted(its, key=lambda i: i["x"])
                                 if len(it["text"].strip()) >= 2]
                        raw = "".join(texts) or None
        except Exception as e:  # noqa: BLE001
            err = str(e)
        name, is_group, count = _rg.parse_title(raw or "")
        det = _rg.detect_chat_type(raw or "", is_group=is_group, member_count=count)
        return {"ok": True, "raw": raw or "", "name": name, "is_group": bool(is_group),
                "member_count": count, "error": err,
                "chat_type": det.get("chat_type"),
                "chat_type_label": _rg.chat_type_label(det.get("chat_type", "")),
                "chat_type_reason": det.get("reason", "")}

    @_safe
    def debug_filter(self, name: str = "", title: str = "") -> dict:
        """返回名称和标题的过滤结果、归一化文本及当前规则，不修改会话。"""
        from . import filters as _filters

        chat = str(name or "")
        raw = str(title or "")
        blocked, reason = _filters.is_blocked(chat, raw or None)
        norm = _filters._norm(chat)
        return {"ok": True, "input": chat, "title": raw, "blocked": bool(blocked),
                "reason": reason, "normalized": norm,
                "norm_title": _filters._norm(raw) if raw else "",
                "allow": list(_filters._extra_list("FILTER_ALLOW")),
                "extra": list(_filters._extra_list("FILTER_EXTRA")),
                "exact": sorted(_filters.BLOCKED_EXACT),
                "suffix": list(_filters.BLOCKED_SUFFIX),
                "keywords": list(_filters.BLOCKED_KEYWORDS)}

    @_safe
    def debug_dedup(self, chat: str = "", text: str = "", seq: str = "") -> dict:
        """使用独立去重器连续检查两次相同输入，返回指纹和命中原因。"""
        from . import dedup as _dedup

        chat = str(chat or "debug")
        text = str(text or "debug")
        seq = str(seq or "") or _dedup.fingerprint(chat, "", text)
        d = _dedup.OcrDedup()
        first_dup, r1, info1 = d.check(chat, seq, text)
        second_dup, r2, info2 = d.check(chat, seq, text)
        return {"ok": True, "chat": chat, "text": text, "client_seq": seq,
                "first": {"dup": first_dup, "reason": r1, "info": info1},
                "second": {"dup": second_dup, "reason": r2, "info": info2},
                "fingerprint": _dedup.fingerprint(chat, seq, text),
                "window_sec": d.window_sec}

    @_safe
    def debug_messages(self, detect_media: bool = True) -> dict:
        """读取当前会话消息，返回解析结果、媒体摘要和过滤判断，不上报事件。"""
        from . import filters as _filters
        from . import regions as _rg

        backend = getattr(self.rt, "backend", None)
        if backend is None or getattr(backend, "_hwnd", None) is None:
            return {"ok": False, "error": "后端未连接：先在总览页点“启动采集”"}
        msgs = backend.get_messages(None, detect_media=bool(detect_media))
        rows = []
        for m in msgs:
            chat = m.get("chat") or ""
            blocked, reason = _filters.is_blocked(chat, getattr(backend, "_current_title", None))
            rows.append({"id": m.get("id"), "chat": chat, "sender": m.get("sender"),
                         "type": m.get("type"), "text": m.get("content"),
                         "y": m.get("y"), "blocked": bool(blocked),
                         "blocked_reason": reason,
                         "media": [{"kind": b.get("kind"), "x": b.get("x"), "y": b.get("y"),
                                    "w": b.get("w"), "h": b.get("h"),
                                    "text": (b.get("text") or "")[:40],
                                    "filename": b.get("filename", "")}
                                   for b in (m.get("media") or [])]})
        raw_title = getattr(backend, "_current_title", None)
        name, is_group, count = _rg.parse_title(raw_title or "")
        det = _rg.detect_chat_type(raw_title or "", is_group=is_group, member_count=count)
        return {"ok": True, "count": len(rows), "rows": rows[:80],
                "title": {"raw": raw_title or "", "name": name,
                          "is_group": bool(is_group), "member_count": count,
                          "chat_type": det.get("chat_type"),
                          "chat_type_label": _rg.chat_type_label(det.get("chat_type", "")),
                          "chat_type_reason": det.get("reason", "")},
                "region_origin": list(getattr(backend, "_last_region_origin", None) or [])}

    @_safe
    def debug_send(self, chat: str = "", text: str = "", dry_run: bool = True) -> dict:
        """预检输入框、过滤和目标类型；dry_run 为假时切换会话并发送文本。

        实际类型仅记录到结果，不与预期类型比较。
        """
        from . import sender as _sender

        backend = getattr(self.rt, "backend", None)
        if backend is None or getattr(backend, "_hwnd", None) is None:
            return {"ok": False, "error": "后端未连接：先在总览页点“启动采集”"}
        hwnd = backend._hwnd
        rect = _sender.input_box_rect(hwnd)
        if rect is None:
            return {"ok": False, "error": "定位不到输入框（窗口尺寸/三区域错位？）"}
        out = {"ok": True, "input_box": list(rect), "chat": chat or "",
               "dry_run": bool(dry_run)}
        if chat:
            from . import filters as _filters
            blocked, reason = _filters.is_blocked(chat)
            out["blocked"] = bool(blocked)
            out["blocked_reason"] = reason
            # 目标会话类型：按会话名判定（私信/群聊），发送时还会读标题复验
            from . import regions as _rg
            det = backend.resolve_chat_type(chat)
            out["chat_type"] = det.get("chat_type")
            out["chat_type_label"] = _rg.chat_type_label(det.get("chat_type", ""))
            out["chat_type_reason"] = det.get("reason", "")
            if not dry_run and not blocked:
                try:
                    ok = backend.ensure_chat(chat)
                    out["switched"] = bool(ok)
                    if ok:
                        # 记录切换后的实际类型；此调试入口不进行类型一致性校验。
                        actual = backend.current_chat_type()
                        out["actual_chat_type"] = actual
                        out["actual_chat_type_label"] = _rg.chat_type_label(actual)
                        ok2 = _sender.send_text(hwnd, chat, text or "txrui调试消息")
                        out["sent"] = bool(ok2)
                        out["message"] = "已发送" if ok2 else "视觉发送失败（输入框定位/粘贴失败）"
                    else:
                        out["message"] = "切不到目标会话"
                except Exception as e:  # noqa: BLE001
                    out["message"] = f"异常: {e}"
        return out

    @_safe
    def debug_files(self, name: str = "") -> dict:
        """列出接收目录，可按显示名查找文件，并检查剪贴板能否读取文件字节。"""
        from . import media_grab as _mg

        dirs = _mg._file_dirs()
        found = None
        if name:
            try:
                found = _mg.find_file_on_disk(str(name))
            except Exception as e:  # noqa: BLE001
                found = None
        return {"ok": True, "dirs": dirs, "query": str(name or ""),
                "found": found, "has_clipboard": _mg._clipboard_file_bytes() is not None
                if hasattr(_mg, "_clipboard_file_bytes") else False}

    @_safe
    def debug_voice(self) -> dict:
        """返回转写地址、最近音频候选及虚拟声卡通道可用性，不调用转写服务。"""
        from . import config as C
        from . import voice as _voice

        ep = str(C.ASR_ENDPOINT or "").strip()
        info = {"ok": True, "asr_endpoint": ep,
                "asr_configured": bool(ep), "recent_audio": [], "error": ""}
        try:
            import time as _t
            p = _voice.find_recent_audio(_t.time() - 3600)
            if p:
                info["recent_audio"] = [p]
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
        try:
            from . import voice_send as _vs
            info["voice_channel"] = bool(_vs.is_available())
        except Exception:
            info["voice_channel"] = False
        return info

