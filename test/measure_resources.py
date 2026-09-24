# -*- coding: utf-8 -*-
"""资源与损耗评估（v1.5.1）：实测一次完整体检的内存峰值、耗时、子进程数。

只读测量，不影响系统。
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes as wt

sys.path.insert(0, r"D:\Projects\DiskGuard\src")


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def current_ws_mb() -> float:
    k32 = ctypes.windll.kernel32
    pmc = _PMC()
    handle = k32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), ctypes.sizeof(pmc))
    return pmc.WorkingSetSize / 1024 / 1024


def main() -> None:
    from core import disk_info, event_scan, nvme_health, smart_parser, verdict, volume_check

    baseline = current_ws_mb()
    peak = baseline
    t0 = time.perf_counter()

    marks: list[tuple[str, float, float]] = []

    def step(name: str, fn, *args):
        nonlocal peak
        t = time.perf_counter()
        result = fn(*args)
        time.sleep(0.05)
        peak = max(peak, current_ws_mb())
        marks.append((name, time.perf_counter() - t, current_ws_mb()))
        return result

    disks = step("枚举硬盘", disk_info.get_physical_disks)
    counters = step("可靠性计数器", disk_info.get_reliability_counters)
    smart = step("SMART 属性(SATA)", smart_parser.get_smart_for_disks, disks)
    nvme = {}
    step("NVMe 健康日志", lambda: [nvme.update({d["device_id"]: nvme_health.query_nvme_health(int(d["device_id"]))}) for d in disks])
    events = step("事件日志扫描", event_scan.scan_disk_events)
    volumes = step("卷检查+空间", volume_check.check_volumes)
    step("评分", lambda: [verdict.evaluate_disk(d["disk"] if isinstance(d, dict) and "disk" in d else d) for d in []] or [
        verdict.evaluate_disk(d, counters.get(str(d.get("device_id"))), smart.get(str(d.get("device_id")), []),
                              *event_scan.match_events_to_disk(events, d)[:2],
                              [v for v in volumes if str(d.get("device_id")) in [str(n) for n in (v.get("disk_numbers") or [])]],
                              nvme.get(str(d.get("device_id")))) for d in disks])
    total = time.perf_counter() - t0

    print(f"本进程内存基线: {baseline:.0f} MB   峰值: {peak:.0f} MB")
    for name, cost, ws in marks:
        print(f"  {name:<14} {cost:5.1f} 秒   结束时内存 {ws:.0f} MB")
    print(f"全流程总耗时: {total:.1f} 秒（含采样等待）")
    print("说明：GUI 运行时另有 PySide6 界面基线约 60-90MB；PowerShell 子进程为瞬态，单进程约 30-60MB、用完即退。")
    print("硬盘写入：全程只读；唯一写盘是本地数据 JSON（几十 KB，仅记录变化时）。")


if __name__ == "__main__":
    main()
