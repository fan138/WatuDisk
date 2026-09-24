# -*- coding: utf-8 -*-
"""系统空闲判断（v1.3）：定时体检只在电脑空闲时进行，绝不添乱。

三个信号（全部只读系统状态，毫秒级）：
- 用户多久没动键鼠（GetLastInputInfo）；
- CPU 空闲率（GetSystemTimes 两次采样差值）；
- 显卡不参与判断——本软件检测只耗极少的 CPU，与显卡无关；
  硬盘繁忙度用「CPU 高位 + 用户活跃」间接规避（直接读磁盘队列
  计数需要常驻性能计数器，得不偿失）。

判定规则（宽松）：用户闲置 ≥5 分钟，或 CPU 忙碌度 <25%，即视为
空闲可以体检；否则推迟 15 分钟重试。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

IDLE_USER_SECONDS = 5 * 60        # 用户闲置阈值
CPU_BUSY_THRESHOLD = 25.0         # CPU 忙碌度阈值（%）
DEFER_SECONDS = 15 * 60           # 繁忙时推迟重试间隔


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def user_idle_seconds() -> float:
    """距离用户最后一次键鼠输入的秒数；获取失败返回 0（视为活跃）。"""
    try:
        info = _LastInputInfo()
        info.cbSize = ctypes.sizeof(_LastInputInfo)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        ticks = ctypes.windll.kernel32.GetTickCount()
        elapsed = (ticks - info.dwTime) & 0xFFFFFFFF
        return elapsed / 1000.0
    except Exception:
        return 0.0


def cpu_busy_percent(sample_ms: int = 500) -> float:
    """在 sample_ms 时间窗内采样 CPU 忙碌度（0-100）；失败返回 100（视为忙）。"""
    class _FT(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wt.DWORD), ("dwHighDateTime", wt.DWORD)]

    class _SystemTimes(ctypes.Structure):
        _fields_ = [("idle", _FT), ("kernel", _FT), ("user", _FT)]

    def _to_u64(ft: "_FT") -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    try:
        kernel32 = ctypes.windll.kernel32
        first = _SystemTimes()
        if not kernel32.GetSystemTimes(ctypes.byref(first.idle), ctypes.byref(first.kernel), ctypes.byref(first.user)):
            return 100.0
        import time

        time.sleep(max(50, sample_ms) / 1000.0)
        second = _SystemTimes()
        if not kernel32.GetSystemTimes(ctypes.byref(second.idle), ctypes.byref(second.kernel), ctypes.byref(second.user)):
            return 100.0
        idle_delta = _to_u64(second.idle) - _to_u64(first.idle)
        total_delta = (_to_u64(second.kernel) - _to_u64(first.kernel)) + (
            _to_u64(second.user) - _to_u64(first.user)
        )
        if total_delta <= 0:
            return 100.0
        busy = 100.0 * (1.0 - idle_delta / total_delta)
        return max(0.0, min(100.0, busy))
    except Exception:
        return 100.0


def uptime_hours() -> float:
    """系统本次开机至今的小时数（GetTickCount64，64 位不溢出）。"""
    try:
        ms = ctypes.windll.kernel32.GetTickCount64()
        return ms / 1000.0 / 3600.0
    except Exception:
        return 0.0


def uptime_text() -> str:
    """开机时长的友好文案：不足 1 小时显示分钟，否则显示小时。"""
    hours = uptime_hours()
    if hours < 1:
        return f"{max(1, int(hours * 60))} 分钟"
    return f"{hours:.1f} 小时"


def system_is_idle() -> bool:
    """当前是否适合做后台体检。"""
    if user_idle_seconds() >= IDLE_USER_SECONDS:
        return True
    return cpu_busy_percent() < CPU_BUSY_THRESHOLD
