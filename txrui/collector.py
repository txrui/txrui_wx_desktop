"""轮询未读会话，过滤消息、获取媒体并将去重后的事件加入发送队列。

图片优先从查看器复制，失败时裁剪；文件按显示名查找；表情和视频取截图，
语音按时间窗口查找缓存文件。视频预览如实按 PNG 图片上报并标记来源。
每条消息最多处理四个媒体气泡；无数据或上传被拒时生成占位段。
媒体在上传前按消息快照去重，最终事件指纹仍包含媒体上传标识。
队列入队数量不代表服务端已确认接收。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from .dedup import OcrDedup
from .payload import (build_media_segment, message_to_payload,
                      clean_message_text, event_preview, NON_TEXT_PLACEHOLDER)

logger = logging.getLogger(__name__)

#: 媒体检测总开关，与每轮采集参数共同决定是否检测。
MEDIA_ENABLED = True

#: 查找音频缓存时，相对当前时间向前回溯的秒数。
_VOICE_SINCE_OFFSET = 30.0


async def _upload(backend, client, data: bytes, filename: str, mime: str) -> dict:
    """过滤空媒体数据，否则交给客户端上传并返回其结果。"""
    if not data:
        return {"ok": False, "error": "empty"}
    from . import media as _media
    return await client.upload_media(data, filename=filename, mime=mime)


async def _grab_image(backend, client, bubble: dict) -> tuple[bytes, str, str]:
    """优先从查看器复制图片；失败时裁剪缓存气泡，返回字节、文件名和媒体类型。"""
    from . import media as _media
    from . import media_grab as _mg
    kind = str(bubble.get("kind", "image") or "image").lower()
    filename = f"image{_media.ext_for(kind)}"
    mime = _media.guess_mime(kind)
    rect = backend.media_screen_rect(bubble)
    if rect:
        try:
            data = _mg.grab_original_image(rect)
            if data:
                return data, filename, mime
        except Exception as e:  # noqa: BLE001
            logger.debug(f"取原图失败，降级裁剪: {e}")
    # 降级：截屏裁剪
    data = backend.crop_media(bubble)
    return (data or b""), filename, mime


async def _grab_file(backend, client, bubble: dict) -> tuple[bytes, str, str]:
    """按显示名查找并读取文件；未找到时保留文件名，返回空数据。"""
    from . import media as _media
    from . import media_grab as _mg
    display = str(bubble.get("filename") or "").strip()
    if not display:
        display = _mg.extract_file_token(bubble.get("text", "")) or ""
    if not display:
        return b"", "", _media.guess_mime("file")
    path = _mg.find_file_on_disk(display)
    if path:
        data = _mg.read_file_bytes(path)
        if data:
            import os
            return data, os.path.basename(path), _mg.mime_for_path(path)
    # 定位不到本体：占位（文件名仍在）
    return b"", display, _media.guess_mime("file")


async def _grab_emoji(backend, client, bubble: dict) -> tuple[bytes, str, str]:
    """裁剪表情当前帧，优先使用屏幕矩形，失败时使用缓存消息区截图。"""
    from . import media as _media
    from . import media_grab as _mg
    filename = f"emoji{_media.ext_for('emoji')}"
    mime = _media.guess_mime("emoji")
    rect = backend.media_screen_rect(bubble)
    if rect:
        data = _mg.crop_region_bytes(backend, rect)
        if data:
            return data, filename, mime
    data = backend.crop_media(bubble)
    return (data or b""), filename, mime


async def _grab_audio(backend, client, bubble: dict) -> tuple[bytes, str, str]:
    """在配置回溯窗口内查找最近音频并读取；未找到时返回空数据。"""
    from . import media as _media
    from . import media_grab as _mg
    from . import voice as _voice
    since = time.time() - _VOICE_SINCE_OFFSET
    path = _voice.find_recent_audio(since)
    if path:
        data = _mg.read_file_bytes(path)
        if data:
            import os
            return data, os.path.basename(path), _mg.mime_for_path(path)
    return b"", "", _media.guess_mime("audio")


async def _grab_video(backend, client, bubble: dict) -> tuple[bytes, str, str]:
    """裁剪视频预览帧，如实返回 PNG 图片，不冒充视频本体。"""
    from . import media_grab as _mg
    filename = "video_preview.png"
    mime = "image/png"
    rect = backend.media_screen_rect(bubble)
    data = None
    if rect:
        data = _mg.crop_region_bytes(backend, rect)
    if not data:
        data = backend.crop_media(bubble)
    return (data or b""), filename, mime


async def _upload_bubbles(backend, client, bubbles: list[dict]) -> list[dict]:
    """顺序处理前四个气泡；获取失败或上传被拒时生成占位段。

    获取阶段异常在本函数内捕获；上传调用抛出的异常继续传给调用方。
    """
    segs: list[dict] = []
    for b in (bubbles or [])[:4]:
        kind = str(b.get("kind", "image") or "image").lower()
        try:
            if kind == "file":
                data, filename, mime = await _grab_file(backend, client, b)
            elif kind == "emoji":
                data, filename, mime = await _grab_emoji(backend, client, b)
            elif kind == "audio":
                data, filename, mime = await _grab_audio(backend, client, b)
            elif kind == "video":
                data, filename, mime = await _grab_video(backend, client, b)
            else:
                data, filename, mime = await _grab_image(backend, client, b)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"取媒体本体失败（{kind}）: {e}")
            data, filename, mime = b"", "", ""
        if not data:
            # 没拿到本体 → 占位段（绝不伪造 media_id）
            segs.append(build_media_segment(b))
            continue
        up = await _upload(backend, client, data, filename, mime)
        if up.get("ok") and up.get("media_id"):
            url = f"/api/v1/media/blobs/{up['media_id']}"
            b2 = dict(b)
            b2["size"] = len(data)
            b2["text"] = b2.get("filename") or b2.get("text") or filename
            if kind == "video":
                b2["kind"] = "image"
                b2["text"] = "[视频预览]"
            segment = build_media_segment(b2, media_id=up["media_id"], url=url,
                                          mime=up.get("mime", "") or mime)
            if kind == "video":
                segment.setdefault("extra", {}).update(original_type="video", preview=True)
            segs.append(segment)
        else:
            logger.debug(f"媒体上传失败（降级为占位）: {up.get('error', '')}")
            segs.append(build_media_segment(b))
    return segs


def _valid_bubble(bubble) -> bool:
    """保留类型已知且宽高均为有限正数的气泡，用于纯媒体消息判断。"""
    if not isinstance(bubble, dict) or bubble.get("kind") not in NON_TEXT_PLACEHOLDER:
        return False
    import math
    try:
        return all(math.isfinite(float(bubble.get(key, 0))) and float(bubble.get(key, 0)) > 0
                   for key in ("w", "h"))
    except (ValueError, TypeError):
        return False


def _voice_text_hint(text: str) -> str:
    """返回符合候选转写规则的气泡文字，否则返回空串。"""
    from . import voice as _voice
    t = str(text or "").strip()
    if _voice.is_transcribed_voice(t):
        return t
    return ""


async def poll_once(backend, client, account_id: str, dedup: OcrDedup,
                    detect_media: bool = True) -> int:
    from . import state as _st
    from .filters import is_blocked
    # 汇总账号标识、连接器标识和自身标记，作为发送者过滤的补充条件。
    from . import config as _C
    _own = {_C.WECHAT_ACCOUNT_ID.strip(), _C.CONNECTOR_ID.strip(), "self"}
    _own = {x for x in _own if x}
    n = 0
    for (_x, _y) in list(backend.iter_unread_sessions()):
        # 名字由 get_messages 联合OCR给出（读标题），不单独OCR
        try:
            msgs = backend.get_messages(None, detect_media=detect_media and MEDIA_ENABLED)
            # 未读红点会在切入会话后消失；如果 OCR 这一帧暂时没有读到内容，
            # 立即标已读会让该会话失去后续重试机会。短暂等待后补读两次。
            for retry in range(2):
                if msgs:
                    break
                await asyncio.sleep(0.35)
                msgs = backend.get_messages(None, detect_media=detect_media and MEDIA_ENABLED)
            if not msgs:
                logger.warning("切入未读会话后连续三次未识别到消息；跳过标已读以便后续重试")
                _st.log("未读会话连续三次未识别到消息，暂不标已读，将等待后续重试")
                continue
        except Exception as e:
            logger.warning(f"读取失败: {e}")
            _st.log(f"读取失败: {e}")
            continue
        chat = getattr(backend, "_current_title", None) or getattr(backend, "_current_chat", None)
        if not chat:
            continue
        # 公众号/服务号/微信游戏等：拦截，不入史不上报，直接标已读跳过
        from .regions import parse_title, detect_chat_type
        raw_title = getattr(backend, "_current_title", None)
        name, is_group, member_count = parse_title(raw_title or chat)
        # backend 已保存规范会话名；这里仍以 backend 状态为准，避免 OCR 标题
        # 偶发带人数/空格导致群聊被误判为私信。
        if getattr(backend, "_current_is_group", False):
            is_group = True
            # backend 保存的是已去人数后缀的名称，重新 parse 无法恢复人数。
            if member_count is None:
                member_count = getattr(backend, "_current_member_count", None)
        # 会话类型（私信/群聊）统一走 detect_chat_type：入站 payload 与
        # 发送侧共用同一口径，避免两边判法不一致。
        det = detect_chat_type(raw_title or chat, is_group=is_group,
                               member_count=member_count)
        is_group = bool(det.get("is_group"))
        member_count = det.get("member_count")
        chat_type = det.get("chat_type") or ("group" if is_group else "private")
        chat = name or chat
        # 过滤同时使用规范名与原始标题，避免公众号/服务号变体漏拦截。
        blocked, reason = is_blocked(chat, raw_title)
        if blocked:
            _st.note_blocked(chat or "", reason)
            logger.info(f"[过滤] {chat!r} ({reason}) 已跳过不上报")
            _st.log(f"[过滤] {chat!r} ({reason}) 已跳过")
            try:
                backend.mark_session_read()
            except Exception:
                pass
            continue
        candidates = []
        signatures = []
        for m in msgs:
            text = clean_message_text(m.get("content"))
            bubbles = [b for b in (m.get("media") or []) if _valid_bubble(b)]
            mtype = str(m.get("type") or "text").lower()
            # 语音条：OCR 文本可能是「语音自动转文字」的转写，也可能是时长
            if mtype == "audio":
                hint = _voice_text_hint(text)
                if hint:
                    text = hint
            # 纯媒体消息（无文本但有气泡）也要上报
            if (not text or text in ("TIME", "SYSTEM")) and not bubbles:
                continue
            sender = (m.get("sender") or chat or "").strip()
            # 发送者命中自身标识时跳过，避免自身消息重复上报。
            if sender in _own or sender == "self":
                _st.bump("dedup")
                continue
            # 按发送者、原文和媒体描述对齐快照；不使用会随滚动变化的 y，
            # 也不使用每次上传可能重新生成的 media_id。标点（包括 /）保留。
            signatures.append(json.dumps([
                sender, text, mtype,
                [(b.get("kind"), b.get("filename", ""), b.get("text", ""))
                 for b in bubbles],
            ], ensure_ascii=False))
            candidates.append((m, text, bubbles, mtype, sender))
        sequences = dedup.snapshot_sequences(chat, signatures) if candidates else []
        for (m, text, bubbles, mtype, sender), client_seq in zip(candidates, sequences):
            dup, reason, _info = dedup.check(chat, client_seq, text, commit=False)
            if dup:
                _st.bump("dedup")
                logger.debug(f"去重 {reason} {chat!r} {text[:12]!r}")
                continue
            media_segments: list[dict] = []
            if bubbles:
                media_segments = await _upload_bubbles(backend, client, bubbles)
            try:
                payload = message_to_payload(account_id, chat, sender,
                                             text, y=m.get("y"),
                                             client_seq=client_seq,
                                             chat_type=chat_type,
                                             connector_id=client.connector_id,
                                             msg_type=mtype,
                                             media_segments=media_segments)
                # 群人数随事件上报，便于 core 侧展示/校验会话类型。
                extra = dict(payload.get("extra") or {})
                extra["chat_type"] = chat_type
                if is_group and member_count is not None:
                    extra["group_member_count"] = member_count
                payload["extra"] = extra
            except ValueError:
                continue
            client.queue_event(payload)
            dedup.check(chat, client_seq, text)
            _st.push_event(chat, sender,
                           event_preview(text, payload["content"]), chat_type=chat_type)
            n += 1
        # 标已读：点一次输入框清红圈（防同一红圈无限重处理，不切换会话）
        try:
            backend.mark_session_read()
        except Exception:
            pass
    from . import state as _st2
    _st2.set_field("last_poll_ts", int(time.time()))
    _st2.bump("poll")
    return n


async def poll_loop(backend, client, account_id: str, poll_sec: float = 2.0):
    dedup = OcrDedup()
    while True:
        try:
            await poll_once(backend, client, account_id, dedup)
        except Exception as e:
            logger.warning(f"轮询异常: {e}")
        await asyncio.sleep(poll_sec)
