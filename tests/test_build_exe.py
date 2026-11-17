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
            patch.object(build_exe.importlib.util, "find_spec", return_value=object()), \
            patch.object(build_exe.subprocess, "run", return_value=result):
        build_exe.check_environment(ROOT)
    assert "paddlex requires numpy<2.4" in capsys.readouterr().err


def test_strict_dependency_conflicts_fail():
    result = subprocess.CompletedProcess([], 1, "dependency conflict", "")
    with patch.object(build_exe.sys, "platform", "win32"), \
            patch.object(build_exe.importlib.util, "find_spec", return_value=object()), \
            patch.object(build_exe.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError, match="严格依赖检查失败"):
            build_exe.check_environment(ROOT, strict_deps=True)


def test_successful_dependency_check_has_no_warning(capsys):
    result = subprocess.CompletedProcess([], 0, "No broken requirements found.", "")
    with patch.object(build_exe.sys, "platform", "win32"), \
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

