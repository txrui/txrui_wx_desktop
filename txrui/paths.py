"""区分打包资源目录与可持久化的用户配置目录。"""
from pathlib import Path
import sys


def resource_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return resource_dir()
