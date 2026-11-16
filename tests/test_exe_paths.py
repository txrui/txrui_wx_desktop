from pathlib import Path
import sys

from txrui import paths


def test_source_app_dir():
    assert paths.app_dir() == Path(paths.__file__).resolve().parents[1]


def test_frozen_app_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "txrui.exe"))
    assert paths.app_dir() == tmp_path
    assert paths.resource_dir() == Path(paths.__file__).resolve().parents[1]


def test_frozen_config_paths(monkeypatch, tmp_path):
    import importlib
    from txrui import config, region_settings

    with monkeypatch.context() as patch:
        patch.setattr(sys, "frozen", True, raising=False)
        patch.setattr(sys, "executable", str(tmp_path / "txrui.exe"))
        patch.chdir(tmp_path)
        importlib.reload(config)
        importlib.reload(region_settings)
        try:
            assert Path(config.CONFIG_PATH) == tmp_path / "config.toml"
            assert region_settings._PATH == tmp_path / "regions.json"
            config.save_patch({"CONNECTOR_ID": "exe_test"})
            region_settings.save_profile({}, {})
            assert (tmp_path / "config.toml").is_file()
            assert (tmp_path / "regions.json").is_file()
        finally:
            patch.undo()
            importlib.reload(config)
            importlib.reload(region_settings)
