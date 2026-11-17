"""打包预检不应被全局环境中无关项目的依赖冲突阻断。"""
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

import build_exe


ROOT = Path(build_exe.__file__).resolve().parent


def test_global_dependency_conflicts_warn_by_default(capsys):
    result = subprocess.CompletedProcess([], 1, "paddlex requires numpy<2.4\n", "")
    with patch.object(build_exe.sys, "platform", "win32"), \
            patch.object(build_exe, "validate_pythonnet_source"), \
            patch.object(build_exe.importlib.util, "find_spec", return_value=object()), \
            patch.object(build_exe.subprocess, "run", return_value=result):
        build_exe.check_environment(ROOT)
    assert "paddlex requires numpy<2.4" in capsys.readouterr().err


def test_strict_dependency_conflicts_fail():
    result = subprocess.CompletedProcess([], 1, "dependency conflict", "")
    with patch.object(build_exe.sys, "platform", "win32"), \
            patch.object(build_exe, "validate_pythonnet_source"), \
            patch.object(build_exe.importlib.util, "find_spec", return_value=object()), \
            patch.object(build_exe.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError, match="严格依赖检查失败"):
            build_exe.check_environment(ROOT, strict_deps=True)


def test_successful_dependency_check_has_no_warning(capsys):
    result = subprocess.CompletedProcess([], 0, "No broken requirements found.", "")
    with patch.object(build_exe.sys, "platform", "win32"), \
            patch.object(build_exe, "validate_pythonnet_source"), \
            patch.object(build_exe.importlib.util, "find_spec", return_value=object()), \
            patch.object(build_exe.subprocess, "run", return_value=result):
        build_exe.check_environment(ROOT)
    assert capsys.readouterr().err == ""


def test_workspace_retained_on_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with build_exe.build_workspace(tmp_path) as workspace:
            (workspace / "artifact.txt").write_text("new")
            raise RuntimeError("publish failed")
    assert (workspace / "artifact.txt").read_text() == "new"


def test_workspace_removed_on_success(tmp_path):
    with build_exe.build_workspace(tmp_path) as workspace:
        assert workspace.is_dir()
    assert not workspace.exists()


def test_publish_failure_restores_previous_version(tmp_path):
    staged, output = tmp_path / "staged", tmp_path / "txrui"
    staged.mkdir()
    output.mkdir()
    (staged / "version").write_text("new")
    (output / "version").write_text("old")
    original = build_exe.rename_with_retry

    def rename(source, target):
        if source == staged:
            raise PermissionError("access denied")
        original(source, target)

    with patch.object(build_exe, "rename_with_retry", side_effect=rename):
        with pytest.raises(PermissionError):
            build_exe.publish(staged, output)
    assert (output / "version").read_text() == "old"
    assert (staged / "version").read_text() == "new"


def test_transient_windows_access_denied_retries(tmp_path):
    error = PermissionError("busy")
    error.winerror = 5
    with patch.object(Path, "rename", side_effect=[error, None]) as rename, \
            patch.object(build_exe.time, "sleep"):
        build_exe.rename_with_retry(tmp_path / "a", tmp_path / "b")
    assert rename.call_count == 2


def test_bundle_requires_managed_and_native_bridges(tmp_path):
    with pytest.raises(RuntimeError, match="Python.Runtime.dll"):
        build_exe.validate_bundle(tmp_path)
    files = (
        "pythonnet/runtime/Python.Runtime.dll", "pythonnet/runtime/Python.Runtime.deps.json",
        "txrui.netfx.config", "webui/index.html",
        "webview/lib/Microsoft.Web.WebView2.Core.dll",
        "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
        "clr_loader/ffi/dlls/amd64/ClrLoader.dll",
    )
    for name in files:
        path = tmp_path / "_internal" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    build_exe.validate_bundle(tmp_path)


def test_self_test_rejects_stale_report(tmp_path):
    (tmp_path / "self-test.json").write_text('{"ok": true}')
    with patch.object(build_exe.subprocess, "run",
                      return_value=subprocess.CompletedProcess([], 0)):
        with pytest.raises(RuntimeError, match="EXE 自检失败"):
            build_exe.test_bundle(tmp_path / "txrui.exe")
    assert not (tmp_path / "self-test.json").exists()


def test_self_test_rejects_import_only_report(tmp_path):
    def run(*args, **kwargs):
        (tmp_path / "self-test.json").write_text('{"ok": true}')
        return subprocess.CompletedProcess([], 0)
    with patch.object(build_exe.subprocess, "run", side_effect=run):
        with pytest.raises(RuntimeError, match="桌面桥接自检未通过"):
            build_exe.test_bundle(tmp_path / "txrui.exe")


def test_self_test_accepts_edgechromium_report(tmp_path):
    def run(*args, **kwargs):
        (tmp_path / "self-test.json").write_text(
            '{"ok": true, "desktop": {"renderer": "edgechromium"}}')
        return subprocess.CompletedProcess([], 0)
    with patch.object(build_exe.subprocess, "run", side_effect=run):
        assert build_exe.test_bundle(tmp_path / "txrui.exe")["ok"]

