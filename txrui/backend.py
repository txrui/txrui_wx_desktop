"""微信视觉后端：连接窗口、识别未读会话并解析标题、文字和媒体。

消息归属优先使用气泡背景色，位置判定兜底；仅返回最后一条自身文字消息
之后的对方消息。媒体坐标相对消息区，屏幕操作使用缓存的区域原点换算。
发送前通过会话列表定位目标，并重新读取标题确认。
"""
from __future__ import annotations

import logging
import re
import time

from . import badge as _badge
from . import capture as _cap
from . import ocr as _ocr
from . import regions as _rg
from . import scale as _scale
from .visual_settings import value as _v, overrides as _visual

logger = logging.getLogger(__name__)


class TxruiBackend:
    name = "txrui-visual"

    def __init__(self):
        self._hwnd = None
        self._session_region, self._message_region, self._title_region = (
            _rg._SESSION_REGION_RATIO, _rg._MESSAGE_REGION_RATIO, _rg._TITLE_REGION_RATIO)
        self._current_chat: str | None = None
        self._current_title: str | None = None
        self._current_is_group = False
        self._current_member_count: int | None = None
        #: 当前会话类型（private/group），供入站 payload 与发送侧共用
        self._current_chat_type = _rg.CHAT_TYPE_PRIVATE
        self._current_chat_type_reason = ""
        self._selected_color = None
        # 最近一次消息区裁剪图与媒体气泡（供 crop_media 裁切）
        self._last_region = None
        self._last_media: list[dict] = []
        # 消息区区域图左上角的屏幕坐标：气泡 region 坐标 → 屏幕坐标的换算基准
        self._last_region_origin: tuple[int, int] | None = None

    # ---- 连接 ----
    def connect(self) -> bool:
        hwnd = _cap.find_wechat_window()
        if hwnd is None:
            raise RuntimeError("未找到微信窗口（请确认微信已登录）")
        self._hwnd = hwnd
        _cap.ensure_visible(hwnd)
        if _v("window_auto_resize") and not _cap.resize_wechat_window(
                hwnd, round(_v("window_width")), round(_v("window_height"))):
            logger.warning("自动调整微信窗口失败，继续按实际窗口尺寸识别")
        # 还原、调整完成后再查询：多显示器下最终所在屏幕的 DPI 才有效。
        rect = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(hwnd))
        if rect:
            logger.info("微信窗口位置=(%s,%s)，实际尺寸=%sx%s 物理像素", *rect)
        # 将当前显示器的实测缩放写入共享模块，区域和像素阈值据此换算。
        try:
            scale = _cap.monitor_dpi_scale(hwnd)
            if scale:
                applied = _scale.set_active_scale(scale)
                lo, hi = _scale.supported()
                if _scale.out_of_range():
                    logger.warning(f"实测显示缩放 {scale}% 超出支持区间 [{lo},{hi}]%，已钳到 {applied}%")
                else:
                    logger.info(f"显示缩放 {scale}%（生效档 {applied}%，k={_scale.k():.3f}）")
            else:
                logger.warning(f"未能检测显示缩放，按默认档 {_scale.active_scale()}% 口径工作")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"缩放档位探测异常，按默认档工作: {e}")
        shot = _cap.capture_window(hwnd)
        if shot is None:
            raise RuntimeError("PrintWindow 截图失败")
        self._apply_regions(shot.size, shot=shot)
        try:
            import numpy as _np
            _a = _np.asarray(shot.convert("RGB").convert("L"))
            logger.info(f"txrui visual 已连接 hwnd=0x{hwnd:x} {shot.size[0]}x{shot.size[1]} "
                        f"整窗mean={_a.mean():.1f} max={int(_a.max())} "
                        f"缩放={_scale.active_scale()}% "
                        f"title区={self._title_region} session区={self._session_region}")
        except Exception:
            logger.info(f"txrui visual 已连接 hwnd=0x{hwnd:x} {shot.size[0]}x{shot.size[1]}")
        return True

    def _apply_regions(self, size=None, shot=None):
        """按窗口尺寸、当前缩放和截图更新三区域，手动标定优先。"""
        w, h = size if size else _rg.WINDOW_SIZE
        self._session_region, self._message_region, self._title_region = \
            _rg.regions_for_window(w, h, _scale.active_scale(), shot=shot)

    def _shot(self, foreground=True):
        if self._hwnd is None:
            raise RuntimeError("未连接")
        if foreground:
            _cap.foreground(self._hwnd)
        shot = _cap.capture_window(self._hwnd)
        if shot is not None:
            self._apply_regions(shot.size, shot=shot)
        return shot

    # ---- 未读轮询（零OCR）----
    def iter_unread_sessions(self):
        """逐行处理未读红点并产出中心屏幕坐标；已识别为选中行时跳过点击。"""
        if self._hwnd is None:
            return
        _cap.ensure_visible(self._hwnd)
        shot = self._shot(foreground=False)
        if shot is None:
            return
        badges = _badge.detect_red_clusters(shot, region=_visual().get("unread", self._session_region))
        if not badges:
            return
        rect = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(self._hwnd))
        if not rect:
            return
        origin_x, origin_y = rect[:2]
        seen: list = []
        for (bl, bt, br, bb) in sorted(badges, key=lambda b: (b[1], b[0])):
            bcx = origin_x + (bl + br) // 2
            bcy = origin_y + (bt + bb) // 2
            if any(abs(bcy - y) < _scale.px(_v("badge_row_tol")) for y in seen):
                continue
            seen.append(bcy)
            if not self._is_row_selected(bcy):
                if not self._click_row(bcx, bcy):
                    continue
            yield (bcx, bcy)

    def _is_row_selected(self, screen_y: int) -> bool:
        if ((self._selected_color is None and not _v("selected_color_manual"))
                or self._hwnd is None):
            return False
        shot = self._shot(foreground=False)
        if shot is None:
            return False
        w, _h = shot.size
        rect = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(self._hwnd))
        if not rect:
            return False
        py = screen_y - rect[1]
        sample = _visual().get("selected_sample")
        px = min(w - 1, round(sample[0] * w)) if sample else int(w * self._session_region[0]) + round(_v("selected_sample_x"))
        try:
            rgb = shot.convert("RGB").getpixel((px, py))
        except Exception:
            return False
        color = _v("selected_color") if _v("selected_color_manual") else self._selected_color
        return _badge.color_close(rgb, color, tol=_v("selected_tol"))

    def _click_row(self, bcx: int, bcy: int) -> bool:
        try:
            import pyautogui
            _cap.foreground(self._hwnd)
            pyautogui.click(bcx + _scale.px(_v("badge_click_x")),
                            bcy + _scale.px(_v("badge_click_y")))
            time.sleep(0.6)
        except Exception as e:
            logger.warning(f"点击未读行失败: {e}")
            return False
        if self._selected_color is None:
            # 尚无高亮样本时，读到非空标题后采样当前行背景色。
            try:
                if self.read_title(foreground=False):
                    self._learn_selected_row_color(bcy)
            except Exception:
                pass
            return True
        return self._is_row_selected(bcy) or True

    def _learn_selected_row_color(self, screen_y: int) -> None:
        """在指定行采样背景色；手动取色横坐标优先，否则取列表左缘偏移点。"""
        if self._hwnd is None:
            return
        shot = self._shot(foreground=False)
        if shot is None:
            return
        w, _h = shot.size
        rect = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(self._hwnd))
        if not rect:
            return
        py = screen_y - rect[1]
        sample = _visual().get("selected_sample")
        px = min(w - 1, round(sample[0] * w)) if sample else int(w * self._session_region[0]) + round(_v("selected_sample_x"))
        try:
            rgb = shot.convert("RGB").getpixel((px, py))
        except Exception:
            return
        self._selected_color = rgb
        logger.info(f"[高亮] 采样选中行背景色 {rgb}（y={screen_y}）")

    def current_chat_type(self) -> str:
        """返回缓存的会话类型；缓存字段缺失时默认私信。"""
        return getattr(self, "_current_chat_type", _rg.CHAT_TYPE_PRIVATE)

    def resolve_chat_type(self, chat: str) -> dict:
        """仅按会话名的群人数后缀推断类型，不切换窗口；无后缀按私信处理。"""
        from .regions import detect_chat_type
        name = str(chat or "").strip()
        det = detect_chat_type(name)
        det["chat_id"] = name
        return det

    def chat_type_info(self) -> dict:
        """汇总缓存的会话名称、类型、人数、中文标签与识别原因。"""
        from .regions import detect_chat_type, chat_type_label
        raw = getattr(self, "_current_title", None)
        det = detect_chat_type(raw or "",
                               is_group=getattr(self, "_current_is_group", None)
                               if raw else None,
                               member_count=getattr(self, "_current_member_count", None))
        ct = det.get("chat_type") or self.current_chat_type()
        det["chat_type"] = ct
        det["label"] = chat_type_label(ct)
        det["name"] = raw or ""
        det["member_count"] = det.get("member_count")
        det["reason"] = (getattr(self, "_current_chat_type_reason", "")
                         or det.get("reason", ""))
        return det

    def _title_matches(self, title: str | None, target: str) -> bool:
        """去除群人数后缀后比较标题和目标名，不作其他空白归一化。"""
        if not title:
            return False
        from .regions import parse_title
        name, _, _ = parse_title(title)
        if name == target:
            return True
        # 目标可能由调用方直接传了带人数的原始标题；做一次宽松归一比较。
        return parse_title(target)[0] == name

    def _record_chat_type(self, title: str | None) -> None:
        """从非空标题更新规范会话名、类型、人数及识别原因。"""
        from .regions import detect_chat_type, parse_title
        raw = str(title or "").strip()
        if not raw:
            return
        name, is_group, member_count = parse_title(raw)
        det = detect_chat_type(raw, is_group=is_group, member_count=member_count)
        self._current_title = name or raw
        self._current_is_group = bool(det.get("is_group"))
        self._current_member_count = det.get("member_count")
        self._current_chat_type = det.get("chat_type") or _rg.CHAT_TYPE_PRIVATE
        self._current_chat_type_reason = det.get("reason", "")

    def ensure_chat(self, chat: str) -> bool:
        """确认当前标题对应目标；否则在会话列表识别名称、点击后复验标题。

        无法定位或复验失败时返回假，由调用方决定是否中止发送。
        """
        if not chat:
            return False
        try:
            title = self.read_title(foreground=False)
        except Exception:
            title = None
        if self._title_matches(title, chat):
            self._record_chat_type(title)
            return True
        shot = self._shot(foreground=False)
        if shot is None:
            return False
        w, h = shot.size
        sr = self._session_region
        crop = shot.crop((int(w * sr[0]), int(h * sr[1]),
                          int(w * sr[2]), int(h * sr[3])))
        items = _ocr.ocr_image(crop)
        target = chat.strip()
        hit = None
        for it in items:
            t = (it.get("text") or "").strip()
            if t and (t == target or target in t or t in target):
                hit = it
                break
        if hit is None:
            logger.warning(f"[切换] 列表区未找到会话 {chat!r}")
            return False
        rect = _cap._with_per_monitor_dpi(lambda: _cap.window_rect(self._hwnd))
        if not rect:
            return False
        cx = rect[0] + int(w * sr[0]) + hit["x"] + hit["w"] // 2
        cy = rect[1] + int(h * sr[1]) + hit["y"] + hit["h"] // 2
        try:
            import pyautogui
            _cap.foreground(self._hwnd)
            pyautogui.click(cx + _scale.px(_v("chat_click_x")),
                            cy + _scale.px(_v("chat_click_y")))
            time.sleep(0.8)
        except Exception as e:
            logger.warning(f"[切换] 点击会话失败: {e}")
            return False
        try:
            title2 = self.read_title(foreground=False) or ""
            if self._title_matches(title2, chat):
                try:
                    self._learn_selected_row_color(cy)
                except Exception:
                    pass
                self._record_chat_type(title2)
                return True
            logger.warning(f"[切换] 标题复验不过：目标={chat!r} 实际={title2!r}")
        except Exception as e:
            logger.warning(f"[切换] 复验异常: {e}")
        return False

    # ---- 标题 ----
    def read_title(self, foreground=True) -> str | None:
        shot = self._shot(foreground=foreground)
        if shot is None:
            return None
        w, h = shot.size
        box = tuple(round(v * dimension) for v, dimension in
                    zip(self._title_region, (w, h, w, h)))
        crop = shot.crop(box)
        # 小字号英文和人数括号在原尺寸下容易混淆；仅放大标题，不增加
        # 整个消息区的识别开销。OCR 返回的坐标仍对应原裁图。
        items = _ocr.ocr_image(crop, upscale=2.0)
        try:
            import numpy as _np
            _a = _np.asarray(crop.convert("RGB").convert("L"))
            logger.info(f"[标题OCR] 窗口{w}x{h} 坐标={box} 裁剪{crop.size[0]}x{crop.size[1]} "
                        f"缩放={_scale.active_scale()}% min={int(_a.min())} "
                        f"mean={_a.mean():.1f} max={int(_a.max())} 检出{len(items)}块")
            if not items and time.monotonic() - getattr(self, "_title_debug_at", float("-inf")) >= 30:
                from pathlib import Path
                from PIL import ImageDraw
                self._title_debug_at = time.monotonic()
                base = Path.cwd()
                crop.convert("RGB").save(base / "txrui_debug_title.png")
                shot.convert("RGB").save(base / "txrui_debug_window.png")
                marked = shot.convert("RGB")
                ImageDraw.Draw(marked).rectangle(box, outline="red", width=3)
                marked.save(base / "txrui_debug_regions.png")
                logger.warning("[标题OCR] 为空，整窗/裁剪/红框图已保存到 %s/txrui_debug_*.png（30秒限频覆盖）", base)
        except Exception:
            pass
        texts = [it["text"] for it in sorted(items, key=lambda i: i["x"])
                 if it["text"].strip() and it["text"].strip() not in ("...", "…", "···")]
        title = "".join(texts).strip()
        logger.info("[标题OCR] 识别结果=%r", title)
        return title or None

    # ---- 消息读取 ----
    def get_messages(self, chat: str | None, limit: int | None = None,
                     detect_media: bool = False):
        """识别文字和可选媒体，返回自身消息边界之后的对方消息。

        使用气泡颜色和位置判断归属，过滤时间、系统提示及媒体内部文字。
        媒体框相对消息区，同时缓存裁图和屏幕原点供获取媒体使用。
        """
        from .regions import parse_title, detect_chat_type
        title = self.read_title(foreground=True)
        if title:
            name, is_group, member_count = parse_title(title)
            # 标题可能被 OCR 拼接成带人数的原始文本；统一保存规范会话名，
            # 同时保留群聊标记，供入站 payload 与发送目标复验共用。
            self._current_title = name or chat
            self._current_is_group = is_group
            self._current_member_count = member_count
            # 会话类型（私信/群聊）单独存一份：入站 payload 与发送侧共用同一口径。
            det = detect_chat_type(title, is_group=is_group, member_count=member_count)
            self._current_chat_type = det["chat_type"]
            self._current_chat_type_reason = det["reason"]
            if chat is None:
                chat = self._current_title
        shot = self._shot(foreground=False)
        if shot is None or not chat:
            return []
        w, h = shot.size
        region = shot.crop((int(w * self._message_region[0]), int(h * self._message_region[1]),
                             int(w * self._message_region[2]), int(h * self._message_region[3])))
        rw, rh = region.size
        items = _ocr.ocr_image(region)
        from .message_layout import text_is_self, media_contains_text
        bubbles = []
        if detect_media:
            try:
                from . import media as _media
                bubbles = _media.detect_media_bubbles(region, items, _scale.active_scale())
            except Exception as e:
                logger.warning(f"媒体气泡检测失败: {e}")
        # 图片/视频里的字幕、菜单文字不是独立聊天消息，也不能参与自身边界判断。
        items = [it for it in items if not any(
            b["kind"] in ("image", "video", "emoji") and media_contains_text(b, it)
            for b in bubbles)]
        # 先按气泡背景判归属；长消息续行可能位于中线左侧，不能只看文字中心。
        sides = {id(it): text_is_self(region, it) for it in items}
        # 按 y 聚行，但不同发送方的文字不能合并为同一行。
        items.sort(key=lambda i: (i["y"], i["x"]))
        rows: list[list[dict]] = []
        for it in items:
            if (rows and abs(it["y"] - rows[-1][-1]["y"]) < _v("row_merge_y")
                    and sides[id(it)] == sides[id(rows[-1][-1])]):
                rows[-1].append(it)
            else:
                rows.append([it])
        msgs: list[dict] = []
        group_sender_rows: dict[int, str] = {}
        consumed_sender_rows: set[int] = set()
        media_senders: dict[int, str] = {}
        if self._current_is_group:
            # 群聊成员名称通常位于左侧消息气泡上方；名称行应短、靠左，
            # 并且与下一行正文保持较小的垂直间距。识别后从正文中移除。
            incoming_rows = [(idx, row) for idx, row in enumerate(rows)
                             if not sides[id(row[0])]]
            # Media has no OCR body row. Match its immediately preceding nickname
            # before pairing text rows, so the nickname is not emitted as a message.
            for bubble_idx, bubble in enumerate(bubbles):
                if text_is_self(region, bubble):
                    continue
                preceding = [(idx, row) for idx, row in incoming_rows
                             if max(r["y"] + r["h"] for r in row) <= bubble["y"]]
                if not preceding:
                    continue
                idx, row = preceding[-1]
                if idx in consumed_sender_rows:
                    continue
                label = " ".join(r["text"] for r in sorted(row, key=lambda r: r["x"])).strip()
                row_x = min(r["x"] for r in row)
                row_height = max(r["h"] for r in row)
                row_width = max(r["x"] + r["w"] for r in row) - row_x
                gap = bubble["y"] - max(r["y"] + r["h"] for r in row)
                if (0 < len(label) <= 24 and len(row) <= 2
                        and not re.search(r"[，。！？!?：:、]|^[\d\s]+$", label)
                        # OCR 框包含字形外边缘：125% 实测昵称框高 20px，
                        # 旧阈值 18px 会漏配，导致昵称与图片拆成两条事件。
                        and row_height <= max(22, 28 * _scale.k())
                        and row_width <= max(180, rw * 0.28)
                        and row_x < rw * 0.45
                        and abs(bubble["x"] - row_x) <= max(32, row_height * 2)
                        and gap <= max(24, 42 * _scale.k())):
                    media_senders[bubble_idx] = label
                    consumed_sender_rows.add(idx)
            for pos, (idx, row) in enumerate(incoming_rows[:-1]):
                if idx in consumed_sender_rows or idx in group_sender_rows:
                    continue
                label = " ".join(r["text"] for r in sorted(row, key=lambda i: i["x"])).strip()
                next_idx, next_row = incoming_rows[pos + 1]
                row_y = min(r["y"] for r in row)
                row_x = min(r["x"] for r in row)
                row_right = max(r["x"] + r["w"] for r in row)
                next_y = min(r["y"] for r in next_row)
                next_x = min(r["x"] for r in next_row)
                gap = next_y - max(r["y"] + r["h"] for r in row)
                compact_name = (0 < len(label) <= 24
                                and not re.search(r"[，。！？!?：:、]", label)
                                and len(row) <= 2
                                and row_right - row_x <= max(180, rw * 0.28))
                label_height = max(r["h"] for r in row)
                body_height = max(r["h"] for r in next_row)
                # 昵称通常字体较小，或比正文更靠左。同字号、同起点的
                # 两条短正文不能仅因距离近就被当成「昵称 + 正文」。
                name_layout = (label_height <= body_height * 0.85
                               or next_x - row_x >= max(8, label_height * 0.4))
                if (compact_name and name_layout and 0 <= gap <= 42
                        and row_x < rw * 0.45 and next_x >= row_x - 8
                        and next_x < rw * 0.72):
                    group_sender_rows[next_idx] = label
                    consumed_sender_rows.add(idx)
        for row_idx, row in enumerate(rows):
            if row_idx in consumed_sender_rows:
                continue
            text = re.sub(r"\s+", " ", " ".join(r["text"] for r in sorted(row, key=lambda i: i["x"]))).strip()
            if not text or not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text):
                continue
            if re.match(r"^[\d:：\s昨天前天上午下午晚上]+$", text):
                continue
            if text == "发送":
                continue
            is_self = sides[id(row[0])]
            # 群聊优先使用识别到的成员名；未识别到名称时回退为会话名。
            msgs.append({"chat": chat,
                         "sender": "self" if is_self else group_sender_rows.get(row_idx, chat or ""),
                         "content": text, "type": "self" if is_self else "other",
                         "y": row[0]["y"],
                         "_box": {"x": min(r["x"] for r in row),
                                  "y": min(r["y"] for r in row),
                                  "w": max(r["x"] + r["w"] for r in row) - min(r["x"] for r in row),
                                  "h": max(r["y"] + r["h"] for r in row) - min(r["y"] for r in row)}})
        # 只要对方消息（self 仅用于定上沿：取最后一条 self 之后的内容）
        last_self = max([i for i, m in enumerate(msgs) if m["type"] == "self"], default=-1)
        other = [m for m in msgs[last_self + 1:] if m["type"] == "other"]
        # 去掉 TIME/SYSTEM：微信时间行已被正则过滤；系统行（"你已添加"等）按关键词过滤
        out = [m for m in other
               if not re.search(r"你已添加|对方撤回|加入群聊|系统消息", m["content"])
               and not re.fullmatch(
                   r'你(?:修改群名为|将群名(?:修改|更改)为)\s*[“"「『].+[”"」』]',
                   m["content"])]

        # ---- 媒体气泡检测（图片/文件/视频/表情/语音）----
        self._last_region = None
        self._last_media = []
        self._last_region_origin = None
        if detect_media:
            try:
                self._last_region = region
                self._last_media = bubbles
                # 区域图左上角的屏幕坐标：气泡 region 坐标 → 屏幕坐标的换算基准
                wr = _cap.window_rect(self._hwnd) if self._hwnd else None
                if wr:
                    self._last_region_origin = (wr[0] + int(w * self._message_region[0]),
                                                wr[1] + int(h * self._message_region[1]))
                # 媒体也须遵守与文字相同的自身消息/历史边界过滤。
                # 关联必须有二维重叠，不能把邻近的文字随意改成媒体消息。
                from .message_layout import media_contains_text
                self_bottom = max((m["_box"]["y"] + m["_box"]["h"]
                                   for m in msgs if m["type"] == "self"), default=-1)
                for bubble_idx, b in enumerate(bubbles):
                    if text_is_self(region, b) or b["y"] < self_bottom:
                        continue
                    owner = next((m for m in out
                                  if m.get("_box") and media_contains_text(b, m["_box"])), None)
                    if owner is None:
                        owner = {"chat": chat,
                                 "sender": media_senders.get(bubble_idx, chat or ""),
                                 "content": "", "type": "other", "y": b["y"],
                                 "media": []}
                        out.append(owner)
                    owner.setdefault("media", []).append(b)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"媒体气泡检测失败: {e}")
        # 媒体与文字按截图顺序统一输出，limit 也须覆盖纯媒体。
        out.sort(key=lambda m: m["y"])
        if limit:
            out = out[-limit:]
        # 统一输出形如 WeChatMessage
        result = []
        for i, m in enumerate(out):
            bubbles_m = m.get("media", [])
            mtype = "text"
            if bubbles_m:
                # 消息类型取首个媒体气泡的类型（多泡同条消息时以第一个为准）
                mtype = str(bubbles_m[0].get("kind", "image") or "image").lower()
                # 文件气泡：文件名来自 OCR 文本，单独抽出来做显示名
                if mtype == "file":
                    from . import media_grab as _mg
                    fname = _mg.extract_file_token(bubbles_m[0].get("text", ""))
                    if fname:
                        bubbles_m[0]["filename"] = fname
            result.append({"id": f"txrui_{i}", "chat": m["chat"], "sender": m["sender"],
                           "content": m["content"], "type": mtype, "y": m["y"],
                           "media": bubbles_m})
        return result

    def crop_media(self, bubble: dict) -> bytes | None:
        """使用最近缓存的消息裁图裁剪气泡；需先启用媒体检测读取消息。"""
        if self._last_region is None:
            return None
        from . import media as _media
        return _media.crop_bubble(self._last_region, bubble)

    def media_screen_rect(self, bubble: dict) -> tuple[int, int, int, int] | None:
        """将消息区气泡框转换为屏幕物理矩形；缺少缓存原点时返回空值。"""
        if not bubble or self._last_region_origin is None:
            return None
        from . import media_grab as _mg
        box = (int(bubble.get("x", 0)), int(bubble.get("y", 0)),
               int(bubble.get("x", 0)) + int(bubble.get("w", 0)),
               int(bubble.get("y", 0)) + int(bubble.get("h", 0)))
        return _mg.to_screen_rect(box, self._last_region_origin)

    def mark_session_read(self) -> bool:
        """点击当前会话输入框以清除未读状态，不主动切换会话。"""
        try:
            from . import sender as _sender
            return _sender._focus_input(self._hwnd)
        except Exception:
            return False

    def close(self):
        self._hwnd = None
