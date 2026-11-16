"""解析语音时长、判断候选转写文本，并提供音频缓存查找和转写请求。

转写判断仅检查文本形态，不能确认文本确实来自语音。
缓存查找只扫描候选目录的直接子文件，按修改时间选择最近音频。
HTTP 转写为独立工具，采集流程不会在本模块自动播放语音或调用转写服务。
"""
from __future__ import annotations

import logging
import os
import re
import time

logger = logging.getLogger(__name__)

#: 匹配文本末尾的一至三位秒数及引号形式的时长标记。
_DURATION_RE = re.compile(r"(\d{1,3})\s*[\"”'']\s*$")


def parse_voice_duration(text: str) -> int:
    """从语音条 OCR 文本解析时长（秒）。解析不出返回 0。"""
    t = str(text or "").strip()
    m = _DURATION_RE.search(t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    m = re.search(r"(\d{1,3})\s*秒", t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def is_voice_text(text: str) -> bool:
    """OCR 文本是否像语音条（时长标记 / 「语音」字样）。"""
    t = str(text or "").strip()
    if not t:
        return False
    if parse_voice_duration(t) > 0:
        return True
    return "语音" in t


def is_transcribed_voice(text: str) -> bool:
    """识别至少两字符且含汉字或字母的候选文本，排除时长和语音标签。

    该判断仅提供弱提示，不验证文本来源。
    """
    t = str(text or "").strip()
    if not t:
        return False
    if is_voice_text(t):
        return False
    if parse_voice_duration(t) > 0:
        return False
    # 纯数字/纯符号不是转写
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", t):
        return False
    return len(t) >= 2


# ---------------------------------------------------------------- 缓存目录

def _cache_dirs() -> list[str]:
    """微信语音/媒体缓存目录候选。"""
    home = os.path.expanduser("~")
    rels = (
        os.path.join("Documents", "WeChat Files"),
        os.path.join("Documents", "xwechat_files"),
        os.path.join("AppData", "Roaming", "Tencent", "WeChat"),
        os.path.join("AppData", "Roaming", "Tencent", "xwechat"),
    )
    out = []
    for rel in rels:
        p = os.path.join(home, rel)
        if os.path.isdir(p):
            out.append(p)
    return out


def find_recent_audio(since_ts: float, max_scan: int = 6000,
                      max_age_sec: float = 180.0) -> str | None:
    """扫描候选目录直接子文件，返回满足起始时间和最大年龄的最新音频。

    每个目录按 max_scan 限制遍历数量，不递归搜索。
    """
    now = time.time()
    best = None
    best_mtime = 0.0
    for d in _cache_dirs():
        try:
            with os.scandir(d) as it:
                for i, entry in enumerate(it):
                    if i > max_scan:
                        break
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in (".silk", ".amr", ".mp3", ".wav", ".m4a", ".opus"):
                            continue
                        st = entry.stat()
                    except Exception:
                        continue
                    if st.st_mtime < since_ts:
                        continue
                    if now - st.st_mtime > max_age_sec:
                        continue
                    if st.st_mtime > best_mtime:
                        best_mtime = st.st_mtime
                        best = entry.path
        except Exception:
            continue
    if best:
        logger.info(f"[语音] 找到语音文件: {best}")
    return best


# ---------------------------------------------------------------- ASR

def transcribe(audio_path: str, endpoint: str = "", timeout: float = 60.0) -> str:
    """以文件表单调用转写服务，优先读取 JSON 的文本或结果字段。

    非 JSON 响应作为文本返回；未配置、状态码非成功或异常时返回空串。
    """
    ep = str(endpoint or "").strip()
    if not ep:
        return ""
    try:
        import requests
        with open(audio_path, "rb") as f:
            resp = requests.post(ep, files={"file": (os.path.basename(audio_path), f)},
                                 timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"[语音] ASR 返回 {resp.status_code}")
            return ""
        try:
            data = resp.json()
            if isinstance(data, dict):
                return str(data.get("text") or data.get("result") or "").strip()
        except Exception:
            pass
        return str(resp.text or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[语音] ASR 调用失败: {e}")
        return ""


def endpoint_from_config() -> str:
    """从 config 读 ASR 端点（未配置返回空串）。"""
    try:
        from . import config as _C
        return str(getattr(_C, "ASR_ENDPOINT", "") or "").strip()
    except Exception:
        return ""
