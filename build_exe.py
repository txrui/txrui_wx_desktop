"""执行 python build_exe.py 构建免安装 Windows 目录版。"""
from pathlib import Path
import shutil
import subprocess
import sys


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


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("请在 Windows 上构建 Windows EXE。")
    root = Path(__file__).resolve().parent
    # 构建前下载并验证当前 OCR 配置使用的模型，以便随包离线分发。
    from txrui.ocr import get_engine
    if get_engine() is None:
        raise SystemExit("OCR 模型初始化失败，请检查网络和运行依赖后重试。")
    build_icon(root)
    output = root / "dist" / "txrui"
    # 重建会清空输出目录，保留用户已在 EXE 中保存的连接与标定配置。
    settings = {name: (output / name).read_bytes()
                for name in ("config.toml", "regions.json")
                if (output / name).is_file()}
    try:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                        str(root / "txrui.spec")], cwd=root, check=True)
    finally:
        if settings:
            output.mkdir(parents=True, exist_ok=True)
            for name, content in settings.items():
                (output / name).write_bytes(content)
    # 不复制源码目录中的实际令牌或标定；仅保留输出目录原有的用户配置。
    shutil.copy2(root / "config.toml.example", output / "config.toml.example")
    shutil.copy2(root / "README.md", output / "README.md")
    print(f"构建完成：{output / 'txrui.exe'}\n请分发整个 txrui 目录，不能只复制 EXE。")


if __name__ == "__main__":
    main()
