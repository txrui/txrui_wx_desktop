"""从截图连通区域提取媒体候选，结合尺寸、色彩、纹理和文字分类。

带字图片依据文字框外的纹理保留，小表情须有彩色图形证据。
坐标相对输入截图；识别依据和置信度为固定规则说明，不是模型概率。
"""
from __future__ import annotations

import logging
import re
from .visual_settings import value as _v

logger = logging.getLogger(__name__)
_VOICE_MAX_H_AT_175 = 34
_EMOJI_MAX_H_AT_175 = 46
_EMOJI_MAX_W_AT_175 = 90


def _bg_gray(arr) -> int:
    import numpy as np
    if arr.size == 0:
        return 255
    sample = arr.ravel()[::max(1, arr.size // 200000)]
    return int(np.bincount(sample.astype('uint8'), minlength=256).argmax())


def _runs(mask_row) -> list[tuple[int, int]]:
    import numpy as np
    changes = np.diff(np.pad(np.asarray(mask_row, dtype=np.int8), (1, 1)))
    return list(zip(np.flatnonzero(changes == 1).tolist(), np.flatnonzero(changes == -1).tolist()))


def _text_boxes_overlap(box, items, pad=None):
    if pad is None:
        pad = _v("ocr_overlap_pad")
    x0, y0, x1, y1 = box
    return [it for it in items
            if it.get("x", 0) - pad < x1 and it.get("x", 0) + it.get("w", 0) + pad > x0
            and it.get("y", 0) - pad < y1 and it.get("y", 0) + it.get("h", 0) + pad > y0]


def classify_box(bw: int, band_h: int, txt: str, max_file_h: int,
                 voice_max_h: int = _VOICE_MAX_H_AT_175,
                 emoji_max_h: int = _EMOJI_MAX_H_AT_175,
                 emoji_max_w: int = _EMOJI_MAX_W_AT_175) -> str:
    """按尺寸和完整文本标记初分媒体类型；emoji_max_w 参数未使用。"""
    txt = str(txt or "").strip()
    aspect = bw / max(1, band_h)
    if (band_h <= voice_max_h and aspect >= _v("audio_aspect")
            and re.fullmatch(r'\d{1,3}\s*(?:["“”′″\'’]|秒)', txt)):
        return "audio"
    if txt:
        from .media_grab import extract_file_token
        if (band_h <= max_file_h and extract_file_token(txt)
                and re.search(r"\b\d+(?:\.\d+)?\s*(?:[KMGT]B?|字节)\b", txt, re.I)):
            return "file"
        if band_h > voice_max_h and re.fullmatch(r"\d{1,2}[:：]\d{2}", txt):
            return "video"
        return "text"
    if band_h <= emoji_max_h:
        return ""
    return "image"


_DURATION = re.compile(r"(?<!\d)(?:(?:\d{1,2})[:：])?\d{1,2}[:：][0-5]\d(?!\d)")


def detect_media_bubbles(region_img, ocr_items: list[dict], scale_pct: int | None = None) -> list[dict]:
    """返回候选框、类型、文字和规则评分，坐标相对传入截图。

    先提取低对比度连通轮廓，再使用前景、文本和图像特征排除噪声。
    """
    import numpy as np
    from .scale import k as _sk, active_scale
    from .media_vision import component_boxes, visual_features, emoji_evidence

    if region_img is None:
        return []
    rgb = np.asarray(region_img.convert("RGB"), dtype=np.int16)
    gray = np.asarray(region_img.convert("L"), dtype=np.int16)
    if not gray.size:
        return []
    k = max(0.5, float(_sk(active_scale() if scale_pct is None else scale_pct)))
    bg = (round(sum(c*w for c, w in zip(_v("panel_color"), (.299, .587, .114))))
          if _v("panel_color_manual") else _bg_gray(gray))
    diff = np.abs(gray - bg)
    mask = diff > _v("media_bg_diff")
    # 微信文字/表情浅灰气泡与背景只差约 10 个灰阶，须先保留完整轮廓。
    candidates = diff > min(8, _v("media_bg_diff"))
    min_h, min_w = int(_v("media_min_h") * k), int(_v("media_min_w") * k)
    emoji_h, emoji_w = int(_v("emoji_max_h") * k), int(_v("emoji_max_w") * k)
    min_eh, min_ew = int(_v("emoji_min_h") * k), int(_v("emoji_min_w") * k)
    voice_h = int(_v("audio_max_h") * k)
    out = []
    height, width = gray.shape
    for c0, r0, c1, r1 in component_boxes(candidates):
        bw, bh = c1 - c0, r1 - r0
        if bw < min_ew or bh < min_eh:
            continue
        # 两侧的小方块通常是头像；消息区裁剪应包含头像到气泡的间距。
        if (0.75 <= bw / max(1, bh) <= 1.33 and max(bw, bh) <= int(90 * k)
                and (c0 < int(10 * k) or c1 > width - int(10 * k)
                     or (bh >= max(48, emoji_h + int(12*k))
                         and (c0 < int(60*k) or c1 > width - int(60*k))))):
            continue
        texts = sorted(_text_boxes_overlap((c0, r0, c1, r1), ocr_items, pad=0),
                       key=lambda it: (it.get("y", 0), it.get("x", 0)))
        txt = " ".join(str(it.get("text", "") or "") for it in texts).strip()
        block, pixels = mask[r0:r1, c0:c1], rgb[r0:r1, c0:c1]
        text_mask = np.zeros(block.shape, dtype=bool)
        for it in texts:
            # OCR 有时能读出 Unicode 表情，不能把它当正文擦掉。
            if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", str(it.get("text", ""))):
                continue
            x0 = max(c0, int(it.get("x", 0)) - 2)
            y0 = max(r0, int(it.get("y", 0)) - 2)
            x1 = min(c1, int(it.get("x", 0) + it.get("w", 0)) + 2)
            y1 = min(r1, int(it.get("y", 0) + it.get("h", 0)) + 2)
            if x1 > x0 and y1 > y0:
                text_mask[y0-r0:y1-r0, x0-c0:x1-c0] = True
        features = visual_features(pixels, block, text_mask)
        kind = classify_box(bw, bh, txt, int(_v("file_max_h") * k),
                            voice_max_h=voice_h, emoji_max_h=emoji_h, emoji_max_w=emoji_w)
        reason, confidence, duration = "", 0.0, ""
        # 小表情无需达到图片尺寸，但必须有独立的彩色图形与轮廓。
        if (bh <= emoji_h + int(24*k) and bw <= emoji_w + int(24*k)
                and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", txt)
                and emoji_evidence(pixels, block, text_mask)):
            kind, reason, confidence = "emoji", "小尺寸彩色图形，排除正文和气泡底色", 0.88
        elif kind == "audio":
            reason, confidence = "语音条比例、完整秒数标记及非文字图标", 0.86
        elif bw >= min_w and bh >= min_h:
            if kind == "file":
                reason, confidence = "文件名后缀、文件大小及卡片区域", 0.90
            else:
                # 图片上有字幕、菜单文字时，看文字之外是否仍有丰富画面。
                picture = features["texture"] and features["residual"] >= 0.20
                plain_picture = not txt and float(block.mean()) >= max(0.60, _v("media_fill"))
                if kind == "video" or picture or plain_picture:
                    kind, reason, confidence = "image", "大尺寸非文字图形" + ("，含丰富图像纹理" if picture else ""), 0.80
                    # 时长必须在缩略图下部；正文中的时间不能把图片改成视频。
                    for it in texts:
                        token = str(it.get("text", "") or "").strip()
                        match = _DURATION.fullmatch(token)
                        if match and it.get("y", 0) >= r0 + bh * 0.55:
                            kind, duration = "video", match.group(0)
                            reason, confidence = "缩略图画面及下部视频时长 " + duration, 0.94
                            break
                    # 兼容只有时长文字且卡片区域足够大的视频预览。
                    if classify_box(bw, bh, txt, int(_v("file_max_h")*k), voice_max_h=voice_h) == "video" and not duration:
                        # 中部时长可能是图片内容或时间行，保守保留图片。
                        reason += "；时长不在下部，未确认为视频"
                else:
                    continue
        else:
            continue
        if kind not in ("emoji", "image", "video", "file", "audio"):
            continue
        if kind != "emoji" and texts and features["residual"] < _v("media_fill"):
            continue
        item = dict(kind=kind, x=c0, y=r0, w=bw, h=bh, text=txt[:200],
                    reason=reason, confidence=confidence)
        if duration:
            item["duration"] = duration
        out.append(item)
    return sorted(out, key=lambda b: (b["y"], b["x"]))


def crop_bubble(region_img, box: dict, pad: int | None = None) -> bytes | None:
    """按检测框裁出气泡区域，编码为 PNG 字节。"""
    if pad is None:
        pad = _v("bubble_crop_pad")
    try:
        import io
        x0 = max(0, int(box.get("x", 0)) - pad)
        y0 = max(0, int(box.get("y", 0)) - pad)
        x1 = int(box.get("x", 0)) + int(box.get("w", 0)) + pad
        y1 = int(box.get("y", 0)) + int(box.get("h", 0)) + pad
        crop = region_img.crop((x0, y0, x1, y1))
        if crop.width < 8 or crop.height < 8:
            return None
        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.debug(f"裁切气泡失败: {e}")
        return None


def guess_mime(kind: str) -> str:
    return {"image": "image/png", "file": "application/octet-stream",
            "video": "video/mp4", "emoji": "image/png",
            "audio": "audio/amr"}.get(kind, "application/octet-stream")


def ext_for(kind: str, filename: str = "") -> str:
    name = str(filename or "")
    if "." in name:
        tail = name.rsplit(".", 1)[-1].lower()
        if tail.isalnum() and len(tail) <= 8:
            return f".{tail}"
    return {"image": ".png", "file": ".bin", "video": ".mp4",
            "emoji": ".png", "audio": ".amr"}.get(kind, ".bin")


HAS_BINARY = ("image", "file", "video")
