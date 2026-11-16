"""将视觉消息组装为入站事件，统一文本清理、类型归一化和媒体占位。

带媒体标识的段保留标识与元数据；无标识的媒体气泡标记为占位。
表情以文本段和表情标记表示，未知类型按文本处理。
事件指纹包含会话、客户端序号、正文及媒体段的类型和标识。
"""
from __future__ import annotations

import hashlib
import time
import uuid

from .dedup import fingerprint

#: 各媒体类型的显示占位文本。
NON_TEXT_PLACEHOLDER = {
    "image": "[图片]",
    "file": "[文件]",
    "emoji": "[表情]",
    "video": "[视频]",
    "audio": "[语音]",
}

#: 媒体类型分组常量；实际获取方式由采集模块决定。
CAPTURED_KINDS = ("image", "file", "video")

#: 入站事件支持的内容段类型；表情单独转换为文本段。
CORE_SEGMENT_TYPES = ("text", "image", "file", "audio", "video", "quote", "system")

#: 段类型归一：外部别名 -> core 白名单类型
_TYPE_ALIAS = {
    "img": "image", "picture": "image", "photo": "image",
    "doc": "file", "document": "file",
    "mp4": "video", "movie": "video",
    "voice": "audio", "sound": "audio",
    "sticker": "emoji", "emoticon": "emoji",
    "txt": "text", "plain": "text",
}


def clean_message_text(text: str) -> str:
    """过滤空白及 OCR 常见的不可见占位字符，保留正常正文。"""
    return str(text or "").translate(dict.fromkeys(map(ord, "\u200b\ufeff\u2060"))).strip()


def event_preview(text: str, segments: list[dict] | None = None) -> str:
    """事件列表使用可读摘要，纯媒体不会显示成空白。"""
    parts = [clean_message_text(text)] if clean_message_text(text) else []
    for seg in segments or []:
        kind = normalize_type(seg.get("type"))
        extra = seg.get("extra") or {}
        if extra.get("emoji"):
            kind = "emoji"
        if kind in NON_TEXT_PLACEHOLDER:
            label = NON_TEXT_PLACEHOLDER[kind]
            if label not in parts:
                parts.append(label)
        elif kind in ("text", "quote", "system"):
            body = clean_message_text(seg.get("text"))
            if body and body not in parts:
                parts.append(body)
    return " ".join(parts)


def make_client_seq(y: int | None, text: str) -> str:
    h = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"{y or 0}_{h}"


def _place_by_text() -> dict[str, str]:
    return {"[图片]": "image", "[文件]": "file", "[表情]": "emoji",
            "[视频]": "video", "[语音]": "audio"}


def normalize_type(t: str) -> str:
    """将别名转换为支持类型；保留表情中间类型，未知值按文本处理。"""
    t = str(t or "text").strip().lower()
    t = _TYPE_ALIAS.get(t, t)
    if t in CORE_SEGMENT_TYPES:
        return t
    if t == "emoji":
        return "emoji"
    return "text"


def build_media_segment(bubble: dict, media_id: str = "", url: str = "",
                        mime: str = "") -> dict:
    """生成媒体内容段，表情转换为带标记的文本段。

    有媒体标识时记录地址、媒体类型和可用大小；否则标记为占位。
    """
    kind = normalize_type(bubble.get("kind", "image") or "image")
    if kind == "emoji":
        kind = "emoji"
    text = str(bubble.get("text", "") or "")
    if not text:
        text = NON_TEXT_PLACEHOLDER.get(kind, "[媒体]")
    seg: dict = {"type": "text" if kind == "emoji" else kind, "text": text[:500]}
    if media_id:
        seg["media_id"] = str(media_id)[:64]
        if url:
            seg["url"] = str(url)[:2000]
        if mime:
            seg["mime"] = str(mime)[:128]
        extra = {"name": text[:200]}
        if bubble.get("size"):
            extra["size"] = int(bubble.get("size") or 0)
        if bubble.get("kind") == "emoji":
            extra["emoji"] = True
        seg["extra"] = extra
    else:
        extra = {"placeholder": True, "name": text[:200]}
        if kind == "emoji":
            extra["emoji"] = True
        seg["extra"] = extra
    return seg


def message_to_payload(account_id: str, chat: str, sender: str, content: str,
                       y: int | None = None, chat_type: str = "group",
                       connector_id: str = "", msg_type: str = "text",
                       media_segments: list[dict] | None = None,
                       client_seq: str | None = None) -> dict:
    text = clean_message_text(content)
    mtype = normalize_type(msg_type or "text")
    if not text and not media_segments and mtype in ("text", "quote", "system"):
        raise ValueError("空消息不上报")
    # 会话类型只接受私信和群聊标记，其他输入按私信处理。
    ct = str(chat_type or "").strip().lower()
    if ct not in ("private", "group"):
        ct = "private"
    # 纯媒体占位文案转换为对应类型，供接收方区分普通正文与缺失媒体。
    _pb = _place_by_text()
    if mtype == "text" and text in _pb:
        mtype = normalize_type(_pb[text])
    segments: list[dict] = []
    if media_segments:
        # 已提供的媒体段直接采用，不在此重新验证其上传状态。
        segments.extend(media_segments)
    if mtype == "image" and not segments:
        segments = [{"type": "image", "text": text or NON_TEXT_PLACEHOLDER["image"],
                     "extra": {"placeholder": True}}]
    elif mtype == "file" and not segments:
        segments = [{"type": "file", "text": text,
                     "extra": {"name": text, "placeholder": True}}]
    elif mtype == "emoji" and not segments:
        # 表情在 core 侧不是独立段类型，按「文本 + emoji 标记」上报
        segments = [{"type": "text", "text": text or NON_TEXT_PLACEHOLDER["emoji"],
                     "extra": {"emoji": True}}]
    elif mtype == "video" and not segments:
        segments = [{"type": "video", "text": text or NON_TEXT_PLACEHOLDER["video"],
                     "extra": {"placeholder": True}}]
    elif mtype in ("audio",) and not segments:
        segments = [{"type": "audio", "text": text or NON_TEXT_PLACEHOLDER["audio"],
                     "extra": {"placeholder": True}}]
    elif not segments:
        segments = [{"type": "text", "text": text}]
    if not event_preview(text, segments):
        raise ValueError("空消息不上报")
    # 指纹含媒体标识：同文案不同媒体必须视为不同事件
    media_sig = "|".join(f"{s.get('type','')}:{s.get('media_id','')}" for s in segments
                         if s.get("type") != "text" or s.get("media_id"))
    client_seq = client_seq if client_seq is not None else make_client_seq(y, text)
    fp = fingerprint(chat, client_seq, text + "|" + media_sig)
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "connector_id": connector_id,
        "account_id": account_id,
        "chat_id": chat,
        "chat_type": ct,
        "platform_message_id": "",
        "sender": {"platform_user_id": sender, "display_name": sender},
        "content": segments,
        "timestamp": int(time.time()),
        "client_seq": client_seq,
        "fingerprint": fp,
    }
