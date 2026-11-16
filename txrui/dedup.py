"""按会话消息快照对齐和客户端序号去重，仅在内存中保存有界记录。

快照对齐不依赖屏幕坐标或上传标识，同文的不同气泡保留独立序号。
序号与指纹记录按容量裁剪；仍在快照中的序号保留，其余记录按时间过期。
"""
from __future__ import annotations

from collections import OrderedDict
from difflib import SequenceMatcher
import hashlib
import time
import uuid


def fingerprint(chat_id: str, client_seq: str, text: str) -> str:
    src = f"{chat_id}|{client_seq}|{text}"
    return hashlib.sha256(src.encode()).hexdigest()[:32]


class OcrDedup:
    def __init__(self, window_sec: int = 120, max_keep: int = 2000):
        self.window_sec = window_sec
        self.max_keep = max(1, max_keep)
        self._seen_seq: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._seen_fp: OrderedDict[str, float] = OrderedDict()
        self._snapshots: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()

    def snapshot_sequences(self, chat_id: str, signatures: list[str]) -> list[str]:
        """将可见消息与上次快照按顺序对齐，为每个气泡返回稳定的唯一序号。

        相同文字在同一快照中出现多次时，一对一匹配，新增气泡仍获新序号。
        空快照可能来自短暂识别失败，不清除上次快照。快照本身按容量保存，
        不按时间失效，避免静止历史消息超过去重窗口后又被当成新消息。
        """
        if not signatures:
            return []
        previous = self._snapshots.get(chat_id, [])
        sequences = [f"ocr_{uuid.uuid4().hex}" for _ in signatures]
        previous_keys = [item[0] for item in previous]
        # 优先匹配历史尾部与当前顶部，避免「收到、旧消息」滚成
        # 「旧消息、新消息、收到」时把新发的「收到」配回历史第一条。
        overlap = next((size for size in range(min(len(previous), len(signatures)), 0, -1)
                        if previous_keys[-size:] == signatures[:size]), 0)
        history: list[tuple[str, str]] = []
        contained = next((start for start in range(len(previous) - len(signatures), -1, -1)
                          if previous_keys[start:start + len(signatures)] == signatures), None)
        if contained is not None:
            sequences = [item[1] for item in previous[contained:contained + len(signatures)]]
            history.extend(previous)
        elif overlap:
            sequences[:overlap] = [item[1] for item in previous[-overlap:]]
            history.extend(previous)
            history.extend(zip(signatures[overlap:], sequences[overlap:]))
        else:
            matcher = SequenceMatcher(None, previous_keys, signatures, autojunk=False)
            for tag, a0, a1, b0, b1 in matcher.get_opcodes():
                if tag == "equal":
                    sequences[b0:b1] = [item[1] for item in previous[a0:a1]]
                    history.extend(previous[a0:a1])
                else:
                    # OCR 暂时漏掉的旧行保留，重新识别出来时仍能匹配。
                    history.extend(previous[a0:a1])
                    history.extend(zip(signatures[b0:b1], sequences[b0:b1]))
        self._snapshots[chat_id] = history[-self.max_keep:]
        self._snapshots.move_to_end(chat_id)
        total = sum(len(items) for items in self._snapshots.values())
        while total > self.max_keep:
            _, items = self._snapshots.popitem(last=False)
            total -= len(items)
        return sequences

    def check(self, chat_id: str, client_seq: str, text: str,
              now: float | None = None, *, commit: bool = True):
        """检查重复；commit=False 用于上传前预检，成功入队后再提交。"""
        now = now if now is not None else time.time()
        active_sequences = {(chat, seq) for chat, items in self._snapshots.items()
                            for _, seq in items}
        for records in (self._seen_seq, self._seen_fp):
            for key, ts in list(records.items()):
                if now - ts > self.window_sec and not (
                        records is self._seen_seq and key in active_sequences):
                    del records[key]
        seq_key = (chat_id, client_seq)
        if client_seq and seq_key in self._seen_seq:
            self._seen_seq[seq_key] = now
            self._seen_seq.move_to_end(seq_key)
            return True, "dup_seq", {"chat_id": chat_id, "client_seq": client_seq}
        fp = fingerprint(chat_id, client_seq, text)
        if fp in self._seen_fp:
            self._seen_fp[fp] = now
            self._seen_fp.move_to_end(fp)
            return True, "dup_fp_window", {"fp": fp}
        if commit:
            if client_seq:
                self._seen_seq[seq_key] = now
            self._seen_fp[fp] = now
            for records in (self._seen_seq, self._seen_fp):
                while len(records) > self.max_keep:
                    records.popitem(last=False)
        return False, "", {"fp": fp}
