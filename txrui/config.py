"""从配置文件和环境变量加载连接、采集、页面及媒体参数。

非空环境变量优先于文件，文件优先于默认值；读取使用标准库 TOML 解析器。
保存仅接受已声明键，通过临时文件替换配置并刷新模块变量。
"""
from __future__ import annotations

import os

# ---- 文件定位：兼容从项目根 / txrui_desktop 子目录 / 任意 cwd 启动 ----
_HERE = os.path.dirname(os.path.abspath(__file__))
from .paths import app_dir

_PROJECT_ROOT = str(app_dir())
_CANDIDATES = (
    os.path.join(_PROJECT_ROOT, "config.toml"),
    os.path.join(os.getcwd(), "config.toml"),
    os.path.join(os.getcwd(), "txrui_desktop", "config.toml"),
)

CONFIG_PATH = next((p for p in _CANDIDATES[:3] if os.path.isfile(p)),
                   os.path.join(_PROJECT_ROOT, "config.toml"))

DEFAULTS: dict[str, str] = {
    "CORE_WS_URL": "ws://127.0.0.1:8000/api/v1/connector/ws",
    "CONNECTOR_ID": "txrui_001",
    "CONNECTOR_TOKEN": "",
    "WECHAT_ACCOUNT_ID": "wx_001",
    "POLL_SEC": "2.0",
    "HEARTBEAT_SEC": "25",
    "WEB_HOST": "127.0.0.1",
    "WEB_PORT": "17880",
    "FILTER_EXTRA": "",
    "FILTER_ALLOW": "",
    "ASR_ENDPOINT": "",
    "WECHAT_FILE_DIRS": "",
    # ---- AstrBot 直连（替代 core 直连）----
    "ASTRBOT_ENABLED": "0",
    "ASTRBOT_WS_URL": "ws://127.0.0.1:8788",
    "ASTRBOT_TOKEN": "",
}

# 配置常量名到文件分节和键名的映射。
_KEYMAP: dict[str, tuple[str, str]] = {
    "CORE_WS_URL": ("core", "ws_url"),
    "CONNECTOR_ID": ("core", "connector_id"),
    "CONNECTOR_TOKEN": ("core", "connector_token"),
    "WECHAT_ACCOUNT_ID": ("core", "account_id"),
    "POLL_SEC": ("collect", "poll_sec"),
    "HEARTBEAT_SEC": ("collect", "heartbeat_sec"),
    "WEB_HOST": ("web", "host"),
    "WEB_PORT": ("web", "port"),
    "FILTER_EXTRA": ("filter", "extra"),
    "FILTER_ALLOW": ("filter", "allow"),
    "ASR_ENDPOINT": ("media", "asr_endpoint"),
    "WECHAT_FILE_DIRS": ("media", "wechat_file_dirs"),
    "ASTRBOT_ENABLED": ("astrbot", "enabled"),
    "ASTRBOT_WS_URL": ("astrbot", "ws_url"),
    "ASTRBOT_TOKEN": ("astrbot", "token"),
}
# 反查：(section, key) -> UPPER_KEY
_REVERSE: dict[tuple[str, str], str] = {v: k for k, v in _KEYMAP.items()}


def _read_toml_file(path: str) -> dict:
    """读取分节或扁平配置并转换为字符串值；文件缺失或解析失败返回空字典。"""
    try:
        with open(path, "rb") as f:
            import tomllib
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(v, dict):  # [section]
            for sk, sv in v.items():
                uk = _REVERSE.get((str(k), str(sk)))
                if uk is not None and not isinstance(sv, (dict, list)):
                    out[uk] = str(sv)
        else:  # 顶层扁平 CORE_WS_URL = "..."
            uk = str(k).upper()
            if uk in DEFAULTS and not isinstance(v, (dict, list)):
                out[uk] = str(v)
    return out


def _merged() -> dict[str, str]:
    file_vals = _read_toml_file(CONFIG_PATH)
    out = dict(DEFAULTS)
    out.update({k: v for k, v in file_vals.items() if k in out})
    for k in out:  # 环境变量覆盖（容器/CI 常用）；空字符串不覆盖文件值
        v = os.getenv(k)
        if v not in (None, ""):
            out[k] = str(v)
    return out


def get(name: str, default: str = "") -> str:
    m = _merged()
    return m.get(name, os.getenv(name, default))


def refresh() -> dict[str, str]:
    """重新合并文件与环境变量，更新模块变量并转换数值配置类型。"""
    m = _merged()
    g = globals()
    for k, v in m.items():
        g[k] = v
    g["POLL_SEC"] = _to_float(m.get("POLL_SEC", "2.0"), 2.0)
    g["HEARTBEAT_SEC"] = _to_int(m.get("HEARTBEAT_SEC", "25"), 25)
    g["WEB_PORT"] = _to_int(m.get("WEB_PORT", "17880"), 17880)
    return m


def _to_float(v: object, dflt: float) -> float:
    try:
        return float(str(v) or dflt)
    except ValueError:
        return dflt


def _to_int(v: object, dflt: int) -> int:
    try:
        return int(float(str(v) or dflt))
    except ValueError:
        return dflt


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def save_patch(patch: dict) -> list[str]:
    """保存已声明的配置键，更新非空环境变量并刷新内存，返回接受的键名。"""
    allowed = set(DEFAULTS)
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是对象")
    cur = _merged()
    applied: list[str] = []
    for k, v in patch.items():
        if k not in allowed:
            continue
        cur[k] = str(v)
        if str(v) != "":
            os.environ[k] = str(v)
        applied.append(k)
    # 组装 section 结构落盘（数字不加引号，其余加引号）
    sections: dict[str, list[tuple[str, str, bool]]] = {}
    for uk, (sec, sk) in _KEYMAP.items():
        is_num = uk in ("POLL_SEC", "HEARTBEAT_SEC", "WEB_PORT")
        sections.setdefault(sec, []).append((sk, cur.get(uk, DEFAULTS[uk]), is_num))
    lines = ["# txrui_desktop 配置（TOML）。Token 明文只存本机，勿提交。", ""]
    for sec in ("core", "collect", "web", "filter", "media", "astrbot"):
        lines.append(f"[{sec}]")
        for sk, sv, is_num in sections.get(sec, []):
            if is_num:
                try:
                    float(sv)
                    lines.append(f"{sk} = {sv}")
                    continue
                except ValueError:
                    pass
            lines.append(f'{sk} = "{_toml_escape(sv)}"')
        lines.append("")
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, CONFIG_PATH)
    refresh()
    return applied


# 将合并配置导出为模块变量，数值项单独转换类型。
_m = _merged()
CORE_WS_URL: str = _m["CORE_WS_URL"]
CONNECTOR_ID: str = _m["CONNECTOR_ID"]
CONNECTOR_TOKEN: str = _m["CONNECTOR_TOKEN"]
WECHAT_ACCOUNT_ID: str = _m["WECHAT_ACCOUNT_ID"]
POLL_SEC: float = _to_float(_m["POLL_SEC"], 2.0)
HEARTBEAT_SEC: int = _to_int(_m["HEARTBEAT_SEC"], 25)
# 公众号/服务号过滤：逗号分隔，归一化后匹配；ALLOW 优先放行
FILTER_EXTRA: str = _m["FILTER_EXTRA"]
FILTER_ALLOW: str = _m["FILTER_ALLOW"]
WEB_HOST: str = _m["WEB_HOST"] or "127.0.0.1"
WEB_PORT: int = _to_int(_m["WEB_PORT"], 17880)
#: 语音转写服务地址；转写工具使用文件表单请求，采集轮询不会自动调用。
ASR_ENDPOINT: str = _m["ASR_ENDPOINT"]
#: 微信接收文件目录（逗号分隔；留空则自动探测标准位置）
WECHAT_FILE_DIRS: str = _m["WECHAT_FILE_DIRS"]
# ---- AstrBot 直连 ----
#: 是否走 AstrBot 直连（"1" = 连 AstrBot 插件的 WS 服务端；"0" = 连 core）
ASTRBOT_ENABLED: str = _m["ASTRBOT_ENABLED"]
#: AstrBot 插件监听的 WS 地址
ASTRBOT_WS_URL: str = _m["ASTRBOT_WS_URL"]
#: AstrBot 插件的连接令牌（与插件配置里的 token 一致）
ASTRBOT_TOKEN: str = _m["ASTRBOT_TOKEN"]
