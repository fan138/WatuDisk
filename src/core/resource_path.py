# -*- coding: utf-8 -*-
"""应用资源（图标等）路径统一解析。

兼容两种运行形态：
- 开发态：src/assets/；
- PyInstaller onefile：sys._MEIPASS/assets/（由 spec 的 datas 打进包）。

不引入新依赖；取不到资源时返回 None，由调用方优雅降级。
"""
from __future__ import annotations

import os
import sys


def assets_dir() -> str:
    """返回资源目录（不保证存在，调用方自行判断文件是否存在）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(sys.executable))
        return os.path.join(base, "assets")
    # 本模块位于 src/core/ 下，资源在 src/assets/
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets"))


def resource_path(name: str) -> str | None:
    """按文件名解析资源完整路径；文件不存在返回 None。"""
    path = os.path.join(assets_dir(), name)
    return path if os.path.isfile(path) else None


def app_icon_path() -> str | None:
    """应用图标：优先 ico，回退 png 底图；都没有返回 None。"""
    return resource_path("diskguard.ico") or resource_path("diskguard_base.png")
