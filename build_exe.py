"""构建 Windows 目录版；新版本成功生成后才替换旧版本。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager


def build_icon(root: Path) -> Path:
    """将原始 PNG 等比居中，生成包含常用 Windows 尺寸的 ICO。"""
    from PIL import Image, ImageOps

    target = root / "logo.ico"
    with Image.open(root / "logo.png") as source:
        image = ImageOps.contain(source.convert("RGBA"), (256, 256),
                                 Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        canvas.alpha_composite(image, ((256 - image.width) // 2,
                                      (256 - image.height) // 2))
        canvas.save(target, format="ICO", sizes=[(16, 16), (24, 24), (32, 32),
                                                (48, 48), (64, 64), (128, 128),
                                                (256, 256)])
    return target


def validate_pythonnet_source() -> None:
    """阻止把不完整的 Python.NET 安装带进成品。"""
    import pythonnet

    runtime = Path(pythonnet.__file__).resolve().parent / "runtime"
    required = ("Python.Runtime.dll", "Python.Runtime.deps.json")
    missing = [name for name in required if not (runtime / name).is_file()]
    if missing:
        raise RuntimeError(
            "Python.NET 安装不完整，缺少：" + "、".join(missing)
            + "。请在干净的 64 位虚拟环境重新安装 requirements-build.txt。"
        )


def check_environment(root: Path, strict_deps: bool = False) -> None:
    if sys.platform != "win32":
        raise RuntimeError("请在 Windows 上构建 Windows EXE。")
    if sys.implementation.name != "cpython" or sys.maxsize <= 2**32:
        raise RuntimeError("请使用 64 位 CPython 构建（推荐 Python 3.12）。")
    if sys.prefix == sys.base_prefix:
        print("建议先创建并启用项目虚拟环境；当前使用全局 Python 时，"
              "PyInstaller 可能探测并收集无关第三方包。", flush=True)
    required = ("txrui.spec", "launcher.py", "run.py", "logo.png",
                "config.toml.example", "txrui.netfx.config", "README.md",
                "webui/index.html")
    missing_files = [name for name in required if not (root / name).is_file()]
    if missing_files:
        raise RuntimeError("缺少构建文件：" + "、".join(missing_files))
    modules = ("PyInstaller", "PIL", "rapidocr", "onnxruntime", "webview",
               "pythonnet", "clr_loader", "cffi", "pystray", "win32clipboard",
               "websockets", "numpy", "pyautogui", "pyperclip", "sounddevice",
               "soundfile", "pycaw", "tkinter")
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "缺少依赖：" + "、".join(missing) + "\n请使用当前 Python 安装依赖：\n"
            + f'"{sys.executable}" -m pip install -r "{root / "requirements-build.txt"}"'
            + "\n若缺少 tkinter，请通过 Python 安装程序添加 Tcl/Tk 组件。")
    validate_pythonnet_source()
    # pip check 检查整个解释器环境，其他项目的依赖冲突不应直接阻止本项目构建。
    result = subprocess.run([sys.executable, "-m", "pip", "check"], cwd=root,
                            check=False, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        details = (result.stdout + result.stderr).strip()
        advice = ("建议使用独立虚拟环境安装 requirements-build.txt，"
                  "避免修改其他项目所需的依赖。")
        if strict_deps:
            raise RuntimeError(f"严格依赖检查失败：\n{details}\n{advice}")
        print(f"警告：当前 Python 环境的全局依赖检查未通过：\n{details}\n"
              f"{advice}\n继续构建；后续验证 OCR 初始化，默认还会验证成品桌面桥接。",
              file=sys.stderr, flush=True)


def rename_with_retry(source: Path, target: Path) -> None:
    """兼容 Windows 索引器或安全软件造成的短暂占用，不覆盖已有目录。"""
    for attempt in range(6):
        try:
            source.rename(target)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                raise
            time.sleep(0.5)


@contextmanager
def build_workspace(dist: Path):
    """仅在全部成功后删除临时目录；失败时保留成品和诊断数据。"""
    temp = Path(tempfile.mkdtemp(prefix=".txrui-build-", dir=dist))
    try:
        yield temp
    except BaseException:
        print(f"构建工作目录已保留：{temp}\n"
              "若其中 txrui/txrui.exe 已生成，可在排除占用后手动移动整个 txrui 目录，"
              "无需重新打包。", file=sys.stderr, flush=True)
        raise
    else:
        shutil.rmtree(temp)


def publish(staged: Path, output: Path) -> None:
    """保留整个旧目录作为备份；替换失败时恢复，避免损坏已发布版本。"""
    backup = output.with_name(output.name + ".previous")
    if backup.exists():
        raise RuntimeError(f"存在上次保留的备份：{backup}，请确认内容后移走再构建。")
    had_previous = output.exists()
    if had_previous:
        rename_with_retry(output, backup)
    try:
        rename_with_retry(staged, output)
    except OSError as publish_error:
        if had_previous:
            try:
                rename_with_retry(backup, output)
            except OSError as rollback_error:
                raise RuntimeError(
                    f"发布失败：{publish_error}\n恢复旧目录也失败：{rollback_error}\n"
                    f"旧版本保留在：{backup}\n新版本保留在：{staged}"
                ) from publish_error
        raise
    if had_previous:
        # 原目录可能包含日志、媒体等用户数据，保留备份供用户核对。
        print(f"旧版本及其全部数据已保留：{backup}", flush=True)


def validate_bundle(staged: Path) -> None:
    """资源完整性检查始终执行，即使显式跳过动态自检。"""
    internal = staged / "_internal"
    if not internal.is_dir():
        # PyInstaller 6.0-era onedir output placed resources beside the EXE.
        internal = staged
    required = (
        "pythonnet/runtime/Python.Runtime.dll",
        "pythonnet/runtime/Python.Runtime.deps.json",
        "txrui.netfx.config", "webui/index.html",
        "webview/lib/Microsoft.Web.WebView2.Core.dll",
        "webview/lib/Microsoft.Web.WebView2.WinForms.dll",
        "webview/lib/runtimes/win-x64/native/WebView2Loader.dll",
    )
    missing = [name for name in required if not (internal / name).is_file()]
    if not list((internal / "clr_loader").rglob("ClrLoader.dll")):
        missing.append("clr_loader/**/ClrLoader.dll")
    if missing:
        raise RuntimeError("成品缺少 Windows 桌面资源：" + "、".join(missing))


def test_bundle(exe: Path) -> dict:
    """windowed EXE 必须等待退出，并读取本次自检结果而非遗留文件。"""
    report_path = exe.parent / "self-test.json"
    report_path.unlink(missing_ok=True)
    result = subprocess.run([str(exe), "--self-test"], cwd=exe.parent,
                            check=False, timeout=180)
    if result.returncode or not report_path.is_file():
        raise RuntimeError(f"EXE 自检失败（退出码 {result.returncode}），请查看 "
                           f"{exe.parent / 'logs' / 'txrui.log'}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("ok") is not True or report.get("desktop", {}).get("renderer") != "edgechromium":
        raise RuntimeError(f"EXE 桌面桥接自检未通过：{report_path}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action=argparse.BooleanOptionalAction, default=True,
                        help="清理 PyInstaller 缓存后构建（默认启用，--no-clean 使用缓存）")
    parser.add_argument("--self-test", action=argparse.BooleanOptionalAction, default=True,
                        help="发布前运行 OCR/.NET/WebView2 自检（默认启用，最多 180 秒）")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--strict-deps", action="store_true", help="将全局 pip check 依赖冲突视为构建失败")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    try:
        print(f"构建解释器：{sys.executable}", flush=True)
        check_environment(root, strict_deps=args.strict_deps)
        # 在独立进程中预检，避免将 CLR 状态带进 PyInstaller 分析进程。
        if args.self_test:
            subprocess.run([sys.executable, "-c",
                            "from txrui.desktop_runtime import check_desktop_runtime; "
                            "print(check_desktop_runtime())"], cwd=root, check=True, timeout=60)
        # 模型初始化可能下载文件，失败时不触碰旧输出目录。
        from txrui.ocr import get_engine
        if get_engine() is None:
            raise RuntimeError("OCR 模型初始化失败，请检查网络和运行依赖后重试。")
        build_icon(root)
        dist = root / "dist"
        dist.mkdir(exist_ok=True)
        output = dist / "txrui"
        if output.with_name("txrui.previous").exists():
            raise RuntimeError("请先移走 dist/txrui.previous 备份目录，再次构建。")
        # 临时目录与最终目录位于同一分区，发布时可以直接重命名。
        with build_workspace(dist) as temp:
            command = [sys.executable, "-m", "PyInstaller", "--noconfirm",
                       "--distpath", temp, "--workpath", str(root / "build")]
            if args.clean:
                command.append("--clean")
            subprocess.run(command + [str(root / "txrui.spec")], cwd=root, check=True)
            staged = Path(temp) / "txrui"
            exe = staged / "txrui.exe"
            if not exe.is_file():
                raise RuntimeError("构建结束但未找到 txrui.exe，旧版本保持不变。")
            validate_bundle(staged)
            for name in ("config.toml.example", "README.md"):
                shutil.copy2(root / name, staged / name)
            if args.self_test:
                # 只在临时目录自检，不读取旧版本中的令牌或标定配置。
                test_bundle(exe)
                for name in ("config.toml", "self-test.json", "logs"):
                    path = staged / name
                    if path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
            # 仅继承旧成品中的配置，绝不打包源码目录的真实令牌。
            for name in ("config.toml", "regions.json"):
                if (output / name).is_file():
                    shutil.copy2(output / name, staged / name)
            publish(staged, output)
        print(f"构建完成：{output / 'txrui.exe'}\n请分发整个 txrui 目录，不能只复制 EXE。", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"\n构建失败：{exc}", file=sys.stderr)
        if isinstance(exc, PermissionError):
            print("文件访问被拒绝：请检查目录权限，并完全退出正在使用成品目录的客户端后重试。",
                  file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
