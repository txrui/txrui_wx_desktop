"""Windows 无控制台 EXE 入口；日志和配置保存在 EXE 旁边。"""
from __future__ import annotations

import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import runpy
import sys


def main() -> int:
    from txrui.paths import app_dir, resource_dir

    home = app_dir()
    try:
        os.chdir(home)
        logs = home / "logs"
        logs.mkdir(exist_ok=True)
        handler = RotatingFileHandler(logs / "txrui.log", maxBytes=5 * 1024 * 1024,
                                      backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                            handlers=[handler], force=True)
        # PyInstaller 的 windowed 模式没有标准输出，第三方库仍可能调用 print。
        for name in ("stdout", "stderr"):
            if getattr(sys, name) is None:
                setattr(sys, name, open(logs / f"{name}.log", "a", encoding="utf-8",
                                        buffering=1))
        config = home / "config.toml"
        if not config.exists():
            template = resource_dir() / "config.toml.example"
            # x 模式避免并发首次启动覆盖另一进程创建的配置。
            try:
                with config.open("x", encoding="utf-8") as stream:
                    stream.write(template.read_text(encoding="utf-8"))
            except FileExistsError:
                pass
        if "--self-test" in sys.argv:
            import json
            from txrui import config as C, region_settings
            from txrui.ocr import get_engine
            from txrui.webserver import WEBUI_DIR
            from txrui.desktop_runtime import check_desktop_runtime
            desktop = check_desktop_runtime()
            import pystray
            import win32clipboard
            import onnxruntime
            assert (Path(WEBUI_DIR) / "index.html").is_file(), "缺少网页资源"
            assert Path(C.CONFIG_PATH) == config, "主配置路径错误"
            assert region_settings._PATH == home / "regions.json", "区域配置路径错误"
            assert get_engine() is not None, "OCR 初始化失败"
            (home / "self-test.json").write_text(json.dumps({
                "ok": True, "desktop": desktop, "config": str(config), "webui": WEBUI_DIR,
                "onnxruntime": onnxruntime.__version__,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0
        runpy.run_path(str(resource_dir() / "run.py"), run_name="__main__")
        return 0
    except Exception:
        logging.exception("txrui 启动失败")
        if "--self-test" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(
                None, f"启动失败，请查看日志：\n{home / 'logs' / 'txrui.log'}",
                "txrui 启动失败", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
