"""按会话名和标题过滤系统入口及指定账号，允许名单优先。

匹配前清理引号和空白，再依次检查精确名称、后缀与关键词。
附加规则读取配置模块内存值，本模块只返回判断结果和原因。
"""
from __future__ import annotations

import re

_QUOTE_CHARS = "“”‘’«»‹›「」『』\"'´`″＂﹝﹞"


def _norm(name: str) -> str:
    s = str(name or "").strip()
    for ch in _QUOTE_CHARS:
        s = s.replace(ch, "")
    return re.sub(r"\s+", "", s)


def _extra_list_from_raw(raw: str) -> list[str]:
    return [_norm(x) for x in re.split(r"[,，;；|]", raw or "") if _norm(x)]


def _extra_list(env_key: str) -> list[str]:
    # 走内存全局（config.refresh 在保存时更新），避免每条消息都读一次文件
    from . import config as _C
    return _extra_list_from_raw(getattr(_C, env_key, "") or "")


def is_blocked(chat: str | None, title: str | None = None) -> tuple[bool, str]:
    """返回拦截标记与原因；允许规则优先于所有拦截规则。"""
    cands = [_norm(chat), _norm(title)]
    cands = [c for c in cands if c]
    if not cands:
        return False, ""
    # 白名单优先：命中即放行
    for allow in _extra_list("FILTER_ALLOW"):
        if any(c == allow or allow in c or c in allow for c in cands):
            return False, ""
    extra = _extra_list("FILTER_EXTRA")
    for exact in extra:
        if any(c == exact for c in cands):
            return True, f"exact:{exact}"
    for c in cands:
        for kw in extra:
            if kw and kw in c:
                return True, f"keyword:{kw}"
    return False, ""
