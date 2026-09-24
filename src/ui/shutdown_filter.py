# -*- coding: utf-8 -*-
"""关机 / 重启守护过滤器（v1.3）。

监听 Windows 消息 WM_QUERYENDSESSION（用户正在关机 / 重启 / 注销），
在系统给应用的处理窗口内做一次「毫秒级」NVMe 健康日志快速复查：
- 只读、不扫描、对硬盘零伤害；总预算 2 秒，超时立即放行；
- 永远不拦截关机（返回 True，让系统正常继续）；
- 发现异常：尽力弹气泡 + 写入「待警示」标记，下次开机郑重提醒。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time

from PySide6.QtCore import QAbstractNativeEventFilter

from core import shutdown_guard
from core.store import get_store

WM_QUERYENDSESSION = 0x0011


class ShutdownGuardFilter(QAbstractNativeEventFilter):
    """挂到 QApplication 上监听关机消息。window 需暴露 _results 与 _tray。"""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt 命名约定
        try:
            if event_type == b"windows_generic_msg":
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_QUERYENDSESSION:
                    self._handle_shutdown()
        except Exception:
            pass  # 守护逻辑绝不影响正常关机
        return False, 0  # 永远放行：不拦截关机

    def _handle_shutdown(self) -> None:
        results = getattr(self._window, "_results", None) or []
        device_ids = [
            str((result.get("disk") or {}).get("device_id") or "")
            for result in results
            if result.get("disk")
        ]
        device_ids = [d for d in device_ids if d]
        if not device_ids:
            return
        deadline = time.time() + shutdown_guard.QUICK_CHECK_TIMEOUT_S
        problems = shutdown_guard.quick_check(device_ids, deadline_ts=deadline)
        if not problems:
            return
        worst = problems[0]
        get_store().set_setting("pending_alert", {
            "device": f"硬盘 {worst['device_id']}",
            "reasons": worst["reasons"],
            "time": time.strftime("%Y-%m-%d %H:%M"),
        })
        tray = getattr(self._window, "_tray", None)
        if tray is not None:
            try:
                tray.notify_custom(
                    "关机前发现硬盘异常",
                    f"{worst['reasons'][0]}——建议下次开机后立即备份数据。",
                    QSystemTrayIcon.MessageIcon.Critical,
                )
            except Exception:
                pass  # 关机过程中气泡可能发不出去，尽力而为
