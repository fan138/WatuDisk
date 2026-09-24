# -*- coding: utf-8 -*-
"""v1.0.0 正式版定稿：品牌更名（DiskGuard/硬盘健康卫士 -> 挖兔硬盘精灵）。
逐文件精确替换并报告结果。
"""
import io
import os

SRC = r"D:\Projects\DiskGuard\src"

FILES = [
    "main.py",
    r"core\report.py",
    r"core\store.py",
    r"core\autostart.py",
    r"ui\tray.py",
    r"ui\main_window.py",
    r"ui\__init__.py",
    r"core\__init__.py",
    r"build\diskguard.spec",
]

PAIRS = [
    ("硬盘健康卫士", "挖兔硬盘精灵"),
    ("APP_VERSION = \"v1.8.0\"", "APP_VERSION = \"v1.0.0\""),
    ("APP_VERSION = \"v1.8.0\"", "APP_VERSION = \"v1.0.0\""),
    ("DiskGuard-LocalInstance", "WatuDiskSprite-LocalInstance"),
    ("DiskGuard.lnk", "WatuDiskSprite.lnk"),
    ("name='DiskGuard'", "name='WatuDiskSprite'"),
    ('name="DiskGuard"', 'name="WatuDiskSprite"'),
    ("DiskGuard 单文件绿色版", "挖兔硬盘精灵 单文件正式版"),
    ("%APPDATA%\\DiskGuard", "%APPDATA%\\WatuDiskSprite"),
    ('os.path.join(appdata, "DiskGuard")', 'os.path.join(appdata, "WatuDiskSprite")'),
    ("diskguard_data.json", "watu_disk_sprite.json"),
    ("DiskGuard 硬盘健康卫士 — 程序入口", "挖兔硬盘精灵 — 程序入口"),
    ("DiskGuard 界面模块包", "挖兔硬盘精灵 界面模块包"),
    ("DiskGuard 硬盘健康卫士 — 核心检测模块包", "挖兔硬盘精灵 — 核心检测模块包"),
    ("DiskGuard 主窗口", "挖兔硬盘精灵 主窗口"),
    ("DiskGuard.exe", "WatuDiskSprite.exe"),
]

results = []
for rel in FILES:
    path = os.path.join(SRC, rel)
    if not os.path.isfile(path):
        results.append(f"[SKIP] {rel} 不存在")
        continue
    with io.open(path, encoding="utf-8") as handle:
        content = handle.read()
    original = content
    for old, new in PAIRS:
        content = content.replace(old, new)
    if content != original:
        with io.open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        results.append(f"[OK]   {rel} 已更新")
    else:
        results.append(f"[SAME] {rel} 无变化")

print("\n".join(results))
