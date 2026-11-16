# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
datas = [(str(root / "webui"), "webui"),
         (str(root / "run.py"), "."),
         (str(root / "config.toml.example"), "."),
         (str(root / "logo.png"), "."),
         (str(root / "logo.ico"), "."),
         (str(root / "logo.png"), "webui")]
binaries = []
hiddenimports = collect_submodules("txrui") + [
    "webview.platforms.winforms", "webview.platforms.edgechromium",
    "pystray._win32", "win32timezone", "PIL.ImageGrab", "PIL.ImageDraw",
]
# 包含 OCR 模型、ONNX 动态库、WebView2/.NET 桥接及音频依赖数据。
for package in ("rapidocr", "onnxruntime", "webview", "pystray", "sounddevice",
                "soundfile", "pycaw"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis([str(root / "launcher.py")], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["torch", "torchvision", "tensorflow", "paddle", "openvino",
                       "matplotlib", "IPython", "notebook", "pytest", "PyQt5",
                       "PyQt6", "PySide2", "PySide6"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="txrui",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root / "logo.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="txrui")
