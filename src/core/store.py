# -*- coding: utf-8 -*-
"""有界持久化存储（v1.4）：体检记录 / 忽略项 / 设置项。

绿色版约定（v1.4 起）：数据统一放 Windows 标准应用数据目录
%APPDATA%\\DiskGuard\\watu_disk_sprite.json——exe 目录保持永远干净
（用户要求不带 data 文件夹），这也是绝大多数 Windows 软件的惯例：
隐藏在用户配置目录里、随软件卸载/手删即无痕。
- 体检记录封顶 MAX_HISTORY 条（默认 200），超出自动淘汰最旧的——
  文件体积与内存占用恒定（约几十 KB），绝不无限增长；
- 写盘时机：仅数据变化时原子写入（临时文件 + os.replace），不留临时垃圾；
- 写入失败静默降级为纯内存模式（功能不受影响，重启后记录丢失）；
- 兼容迁移：若旧版曾把数据存在 exe 旁 data/ 目录，首次运行自动搬过来。

内存占用说明：常驻内存的只有最近 MAX_HISTORY 条记录（结构很小），
不会随使用时间增长。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading

MAX_HISTORY = 200
_DATA_VERSION = 1


def _appdata_dir() -> str:
    """标准应用数据目录：%APPDATA%/DiskGuard。"""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "WatuDiskSprite")


def _legacy_dirs() -> list[str]:
    """旧版数据目录（用于一次性迁移）：
    - DiskGuard 时代：%APPDATA%/DiskGuard；
    - 更早的绿色试验版：exe 旁 data/。
    """
    candidates: list[str] = []
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    candidates.append(os.path.join(appdata, "DiskGuard"))
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data"))
    else:
        candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
    return candidates


def data_file_path(dir_override: str | None = None) -> str:
    """返回实际使用的数据文件完整路径（供测试注入 / 界面显示）。"""
    if dir_override:
        return os.path.join(dir_override, "watu_disk_sprite.json")
    return os.path.join(_appdata_dir(), "watu_disk_sprite.json")


class Store:
    """有界 JSON 存储：线程安全、写入原子、失败降级为内存。"""

    def __init__(self, dir_override: str | None = None) -> None:
        self._lock = threading.Lock()
        self._override = dir_override  # 测试注入标记：非 None 时跳过旧数据迁移
        self._path = data_file_path(dir_override)
        self._data: dict = {"version": _DATA_VERSION, "history": [], "ignored": [], "settings": {}}
        self._writable = True
        self._load()

    # ------------------------------------------------------------------
    @property
    def path(self) -> str:
        return self._path

    def _load(self) -> None:
        self._migrate_legacy()
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                self._data["history"] = list(data.get("history") or [])[-MAX_HISTORY:]
                self._data["ignored"] = list(data.get("ignored") or [])
                self._data["settings"] = dict(data.get("settings") or {})
        except (OSError, ValueError):
            pass  # 首次运行或文件损坏：从空白开始

    def _migrate_legacy(self) -> None:
        """旧版数据文件（DiskGuard 时代的 diskguard_data.json / 更早的
        exe 旁 data/）搬到新位置，改名后删除旧文件。

        dir_override（测试注入）模式下跳过迁移——绝不动真实旧数据。
        """
        if self._override is not None:
            return
        if os.path.isfile(self._path):
            return
        for legacy_dir in _legacy_dirs():
            for legacy_name in ("diskguard_data.json", "watu_disk_sprite.json"):
                legacy_file = os.path.join(legacy_dir, legacy_name)
                if not os.path.isfile(legacy_file):
                    continue
                try:
                    os.makedirs(os.path.dirname(self._path), exist_ok=True)
                    shutil.move(legacy_file, self._path)
                    try:
                        os.rmdir(legacy_dir)  # 空了就顺手删掉，目录保持干净
                    except OSError:
                        pass
                    return
                except OSError:
                    return

    def _save_locked(self) -> None:
        """原子写入；失败进入内存模式（本进程内不再反复尝试写盘）。"""
        if not self._writable:
            return
        try:
            directory = os.path.dirname(self._path)
            os.makedirs(directory, exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            self._writable = False

    # ------------------------------------------------------------------
    # 体检记录
    # ------------------------------------------------------------------
    def append_history(self, entry: dict) -> None:
        """追加一条体检记录（新在前），超出上限自动淘汰最旧。"""
        with self._lock:
            self._data["history"].insert(0, dict(entry))
            del self._data["history"][MAX_HISTORY:]
            self._save_locked()

    def history(self) -> list[dict]:
        """返回体检记录副本（新在前）。"""
        with self._lock:
            return [dict(item) for item in self._data["history"]]

    # ------------------------------------------------------------------
    # 忽略项
    # ------------------------------------------------------------------
    @staticmethod
    def ignore_key(serial: str, metric_key: str) -> str:
        return f"{serial or '?'}|{metric_key}"

    def is_ignored(self, key: str) -> bool:
        with self._lock:
            return key in self._data["ignored"]

    def set_ignored(self, key: str, ignored: bool) -> None:
        with self._lock:
            if ignored and key not in self._data["ignored"]:
                self._data["ignored"].append(key)
            elif not ignored and key in self._data["ignored"]:
                self._data["ignored"].remove(key)
            self._save_locked()

    # ------------------------------------------------------------------
    # 气泡提醒日志（v1.5：桌面表格的数据源，封顶 300 条）
    # ------------------------------------------------------------------
    def append_notify_log(self, entry: dict) -> None:
        """记录一条气泡提醒（时间/级别/标题/内容），封顶自动淘汰。"""
        with self._lock:
            log = list(self._data.get("notify_log") or [])
            log.insert(0, dict(entry))
            del log[MAX_HISTORY:]
            self._data["notify_log"] = log
            self._save_locked()

    def notify_log(self) -> list[dict]:
        """返回气泡提醒日志副本（新在前）。"""
        with self._lock:
            return [dict(item) for item in self._data.get("notify_log") or []]

    # ------------------------------------------------------------------
    # 设置项
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: object = None) -> object:
        with self._lock:
            return self._data["settings"].get(key, default)

    def set_setting(self, key: str, value: object) -> None:
        with self._lock:
            self._data["settings"][key] = value
            self._save_locked()


# 进程级单例（首次访问时初始化；测试可自行构造带 dir_override 的实例）
_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
