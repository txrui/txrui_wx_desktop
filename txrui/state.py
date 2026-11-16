"""以锁保护共享状态、有限容量日志和事件摘要，供控制页面轮询读取。"""
from __future__ import annotations

import collections
import threading
import time

_lock = threading.Lock()
_logs: collections.deque = collections.deque(maxlen=300)
_events: collections.deque = collections.deque(maxlen=100)

state = {
    "running": False,
    "connected": False,       # WS hello_ack 后 True，断线 False
    "backend_ok": False,      # visual connect 成功
    "hwnd": "",
    "core_ws_url": "",
    "connector_id": "",
    "account_id": "",
    "last_error": "",
    "last_poll_ts": 0,
    "last_event_ts": 0,
    "counts": {"poll": 0, "events": 0, "reported": 0, "acked": 0, "blocked": 0,
               "sent_ok": 0, "sent_fail": 0, "dedup": 0},
    "blocked_recent": [],     # 最近被拦的会话名 [(chat, reason, ts)]
}


def log(msg: str) -> None:
    with _lock:
        _logs.append((time.strftime("%H:%M:%S"), str(msg)))


def get_logs(n: int = 200) -> list[tuple[str, str]]:
    with _lock:
        return list(_logs)[-n:]


def push_event(chat: str, sender: str, text: str, chat_type: str = "") -> None:
    """记录非空事件摘要和会话类型，更新事件时间与计数。

    摘要最多保留八十字符；会话类型仅转小写，不在此校验取值。
    """
    from .payload import clean_message_text
    text = clean_message_text(text)
    if not text:
        return
    with _lock:
        _events.append({"ts": time.strftime("%H:%M:%S"), "chat": chat,
                        "sender": sender, "text": (text or "")[:80],
                        "chat_type": str(chat_type or "").strip().lower()})
        state["last_event_ts"] = int(time.time())
        state["counts"]["events"] += 1


def get_events(n: int = 50) -> list[dict]:
    with _lock:
        return list(_events)[-n:][::-1]


def bump(key: str, n: int = 1) -> None:
    with _lock:
        state["counts"][key] = state["counts"].get(key, 0) + n


def set_field(k: str, v) -> None:
    with _lock:
        state[k] = v


def note_blocked(chat: str, reason: str) -> None:
    with _lock:
        state["counts"]["blocked"] += 1
        state["blocked_recent"] = ([(chat, reason, time.strftime("%H:%M:%S"))]
                                   + state["blocked_recent"])[:20]


def snapshot() -> dict:
    with _lock:
        import copy
        return copy.deepcopy(state)
