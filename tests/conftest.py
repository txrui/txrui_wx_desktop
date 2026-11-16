"""为每个测试隔离标定文件路径与缓存，避免影响用户标定配置。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_visual_profile(tmp_path, monkeypatch):
    from txrui import region_settings
    monkeypatch.setattr(region_settings, "_PATH", tmp_path / "test_regions.json")
    monkeypatch.setattr(region_settings, "_CACHE", None)
    monkeypatch.setattr(region_settings, "_VISUAL", {})
