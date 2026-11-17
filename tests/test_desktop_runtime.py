import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from txrui import desktop_runtime


def test_prepare_runtime_passes_app_config_to_netfx(tmp_path, monkeypatch):
    config = tmp_path / "txrui.netfx.config"
    config.write_text("<configuration />", encoding="utf-8")
    runtime = SimpleNamespace(get_runtime_info=Mock(return_value=None), load=Mock())
    monkeypatch.setattr(desktop_runtime.sys, "platform", "win32")
    monkeypatch.setattr(desktop_runtime, "resource_dir", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "pythonnet", runtime)

    desktop_runtime.prepare_desktop_runtime()

    runtime.load.assert_called_once_with("netfx", config_file=str(config))


def test_prepare_runtime_does_not_reload_initialized_netfx(tmp_path, monkeypatch):
    config = tmp_path / "txrui.netfx.config"
    config.write_text("<configuration />", encoding="utf-8")
    runtime = SimpleNamespace(get_runtime_info=Mock(return_value=object()), load=Mock())
    monkeypatch.setattr(desktop_runtime.sys, "platform", "win32")
    monkeypatch.setattr(desktop_runtime, "resource_dir", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "pythonnet", runtime)

    desktop_runtime.prepare_desktop_runtime()

    runtime.load.assert_not_called()


def test_prepare_runtime_reports_missing_config(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_runtime.sys, "platform", "win32")
    monkeypatch.setattr(desktop_runtime, "resource_dir", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="缺少 .NET 加载配置"):
        desktop_runtime.prepare_desktop_runtime()


def test_non_windows_skips_pythonnet(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_runtime.sys, "platform", "linux")
    monkeypatch.setattr(desktop_runtime, "resource_dir", lambda: tmp_path)
    desktop_runtime.prepare_desktop_runtime()


def test_pythonnet_source_requires_runtime_files(tmp_path, monkeypatch):
    package = tmp_path / "pythonnet"
    runtime = package / "runtime"
    runtime.mkdir(parents=True)
    fake = SimpleNamespace(__file__=str(package / "__init__.py"))
    monkeypatch.setitem(sys.modules, "pythonnet", fake)

    with pytest.raises(RuntimeError, match="Python.NET 安装不完整"):
        import build_exe
        build_exe.validate_pythonnet_source()

    for filename in ("Python.Runtime.dll", "Python.Runtime.deps.json"):
        (runtime / filename).write_bytes(b"test")
    build_exe.validate_pythonnet_source()
