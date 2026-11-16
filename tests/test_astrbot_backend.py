"""验证连接目标与令牌选择，以及 AstrBot 配置的默认值、映射和保存。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from txrui import config as C
from txrui.runtime import resolve_ws_target


@pytest.fixture
def clean_env(monkeypatch):
    """清掉 ASTRBOT_* 环境变量，避免宿主机配置干扰。"""
    for key in ("ASTRBOT_ENABLED", "ASTRBOT_WS_URL", "ASTRBOT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestResolveWsTarget:
    def test_default_goes_to_core(self, clean_env):
        """默认（未开启）走 core。"""
        clean_env.setattr(C, "ASTRBOT_ENABLED", "0")
        clean_env.setattr(C, "ASTRBOT_WS_URL", "ws://127.0.0.1:8788")
        clean_env.setattr(C, "ASTRBOT_TOKEN", "")
        clean_env.setattr(C, "CORE_WS_URL", "ws://core:8000/ws")
        clean_env.setattr(C, "CONNECTOR_TOKEN", "core-token")

        ws_url, token, target = resolve_ws_target()
        assert target == "core"
        assert ws_url == "ws://core:8000/ws"
        assert token == "core-token"

    def test_astrbot_enabled_goes_to_astrbot(self, clean_env):
        """开启 AstrBot 直连时连 AstrBot 的地址。"""
        clean_env.setattr(C, "ASTRBOT_ENABLED", "1")
        clean_env.setattr(C, "ASTRBOT_WS_URL", "ws://127.0.0.1:8788")
        clean_env.setattr(C, "ASTRBOT_TOKEN", "astrbot-token")
        clean_env.setattr(C, "CORE_WS_URL", "ws://core:8000/ws")
        clean_env.setattr(C, "CONNECTOR_TOKEN", "core-token")

        ws_url, token, target = resolve_ws_target()
        assert target == "astrbot"
        assert ws_url == "ws://127.0.0.1:8788"
        assert token == "astrbot-token"

    def test_astrbot_token_falls_back_to_connector_token(self, clean_env):
        """专用令牌为空时使用连接器令牌。"""
        clean_env.setattr(C, "ASTRBOT_ENABLED", "1")
        clean_env.setattr(C, "ASTRBOT_WS_URL", "ws://127.0.0.1:8788")
        clean_env.setattr(C, "ASTRBOT_TOKEN", "")
        clean_env.setattr(C, "CONNECTOR_TOKEN", "shared-token")

        _ws_url, token, target = resolve_ws_target()
        assert target == "astrbot"
        assert token == "shared-token"

    def test_enabled_accepts_truthy_strings(self, clean_env):
        """开关接受 1/true/yes/on 各种真值写法。"""
        for truthy in ("1", "true", "TRUE", "yes", "on"):
            clean_env.setattr(C, "ASTRBOT_ENABLED", truthy)
            clean_env.setattr(C, "ASTRBOT_WS_URL", "ws://127.0.0.1:8788")
            clean_env.setattr(C, "ASTRBOT_TOKEN", "t")
            _ws_url, _token, target = resolve_ws_target()
            assert target == "astrbot", f"truthy={truthy!r} 应判定为开启"

    def test_disabled_accepts_falsy_strings(self, clean_env):
        """开关接受 0/false/no/off 各种假值写法。"""
        for falsy in ("0", "false", "FALSE", "no", "off", ""):
            clean_env.setattr(C, "ASTRBOT_ENABLED", falsy)
            clean_env.setattr(C, "CORE_WS_URL", "ws://core:8000/ws")
            clean_env.setattr(C, "CONNECTOR_TOKEN", "t")
            _ws_url, _token, target = resolve_ws_target()
            assert target == "core", f"falsy={falsy!r} 应判定为关闭"


class TestAstrbotConfigKeys:
    def test_defaults_present(self):
        """AstrBot 配置项均提供默认值。"""
        assert "ASTRBOT_ENABLED" in C.DEFAULTS
        assert "ASTRBOT_WS_URL" in C.DEFAULTS
        assert "ASTRBOT_TOKEN" in C.DEFAULTS
        assert C.DEFAULTS["ASTRBOT_ENABLED"] == "0"
        assert C.DEFAULTS["ASTRBOT_WS_URL"] == "ws://127.0.0.1:8788"
        assert C.DEFAULTS["ASTRBOT_TOKEN"] == ""

    def test_keymap_points_to_astrbot_section(self):
        """AstrBot 配置项映射至配置文件的 astrbot 节。"""
        assert C._KEYMAP["ASTRBOT_ENABLED"] == ("astrbot", "enabled")
        assert C._KEYMAP["ASTRBOT_WS_URL"] == ("astrbot", "ws_url")
        assert C._KEYMAP["ASTRBOT_TOKEN"] == ("astrbot", "token")

    def test_save_patch_accepts_astrbot_keys(self, tmp_path, monkeypatch):
        """save_patch 白名单接受 ASTRBOT_* 并落盘。"""
        cfg_path = tmp_path / "config.toml"
        monkeypatch.setattr(C, "CONFIG_PATH", str(cfg_path))
        monkeypatch.setenv("ASTRBOT_ENABLED", "")
        monkeypatch.setenv("ASTRBOT_WS_URL", "")
        monkeypatch.setenv("ASTRBOT_TOKEN", "")

        applied = C.save_patch(
            {
                "ASTRBOT_ENABLED": "1",
                "ASTRBOT_WS_URL": "ws://127.0.0.1:9999",
                "ASTRBOT_TOKEN": "tok",
            }
        )
        assert set(applied) == {"ASTRBOT_ENABLED", "ASTRBOT_WS_URL", "ASTRBOT_TOKEN"}

        content = cfg_path.read_text(encoding="utf-8")
        assert "[astrbot]" in content
        assert 'enabled = "1"' in content
        assert 'ws_url = "ws://127.0.0.1:9999"' in content
        assert 'token = "tok"' in content


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
