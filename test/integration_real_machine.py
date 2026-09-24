# -*- coding: utf-8 -*-
"""真机集成测试：串联 core 全模块真实函数，在本机实际跑通。

验证点：
- 无未捕获异常；
- PowerShell 调用无黑框残留（CREATE_NO_WINDOW 由单元测试 mock 验证 + 此处真机窗口行为验证）；
- 每块物理盘都能给出评分与结论；
- 打印每块盘的检测摘要。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import event_scan, report, smart_parser, verdict, volume_check  # noqa: E402
from core.disk_info import format_hours, format_size, get_physical_disks, get_reliability_counters  # noqa: E402


def main() -> int:
    print("=== DiskGuard 真机集成测试 ===")
    started = time.perf_counter()
    failures: list[str] = []

    # 1) 枚举物理磁盘
    disks = get_physical_disks()
    print(f"\n[1] 物理磁盘枚举：{len(disks)} 块")
    if not disks:
        failures.append("get_physical_disks 返回空（PowerShell 管道异常？）")
    for disk in disks:
        print(
            f"    盘 {disk['device_id']}: {disk['model']} | {disk['bus_type']}/{disk['media_type']}"
            f" | {format_size(disk['size'])} | {disk['health_status']} | SN={disk['serial'] or '无'}"
        )

    # 2) 可靠性计数器
    counters_map = get_reliability_counters()
    print(f"\n[2] 可靠性计数器：{len(counters_map)} 块盘有数据")
    for device_id, counters in counters_map.items():
        print(
            f"    盘 {device_id}: 温度={counters['Temperature']} 磨损={counters['Wear']}"
            f" 通电={format_hours(counters['PowerOnHours'])}"
            f" 未修正读/写错误={counters['ReadErrorsUncorrected']}/{counters['WriteErrorsUncorrected']}"
        )

    # 3) SMART 属性
    smart_map = smart_parser.get_smart_for_disks(disks)
    print(f"\n[3] SATA SMART 属性：{len(smart_map)} 块盘有数据")
    for device_id, attrs in smart_map.items():
        key_ids = (0x05, 0xC5, 0xC6, 0xC7)
        keys = [a for a in attrs if a["id"] in key_ids]
        print(f"    盘 {device_id}: 共 {len(attrs)} 个属性, 关键项 05/C5/C6/C7 = "
              f"{[(a['hex'], a['raw']) for a in keys]}")

    # 4) 事件日志扫描
    events = event_scan.scan_disk_events()
    print(f"\n[4] 最近 30 天磁盘相关错误/警告事件：{len(events)} 条")

    # 5) 卷损坏位
    volumes = volume_check.check_volumes()
    print(f"\n[5] 卷损坏位检查：{len(volumes)} 个卷")
    for volume in volumes:
        print(f"    {volume['drive']} dirty={volume['dirty']} disk={volume['disk_number']}")

    # 6) 评分串联
    print("\n[6] 综合评分")
    results: list[dict] = []
    for disk in disks:
        device_id = str(disk.get("device_id") or "")
        counters = counters_map.get(device_id)
        attrs = smart_map.get(device_id, [])
        event_count, event_recent = event_scan.match_events_to_disk(events, disk)
        disk_volumes = [
            v for v in volumes
            if v.get("disk_number") is not None and str(v.get("disk_number")) == device_id
        ]
        dirty = [v for v in disk_volumes if v.get("dirty")]
        result = {
            "disk": disk,
            "counters": counters,
            "smart_attrs": attrs,
            "event_count": event_count,
            "event_recent": event_recent,
            "dirty_volumes": dirty,
            "all_volumes": disk_volumes,
            "verdict": verdict.evaluate_disk(disk, counters, attrs, event_count, event_recent, dirty),
        }
        results.append(result)
        verdict_data = result["verdict"]
        print(
            f"    盘 {device_id} {disk['model']}: {verdict_data['score']} 分"
            f" [{verdict_data['level_text']}] 事件 {event_count} 条"
        )
        for reason in verdict_data["reasons"]:
            print(f"      · {reason}")

    if disks and not results:
        failures.append("有物理盘但评分结果为空")

    for result in results:
        verdict_data = result["verdict"]
        if not (0 <= verdict_data["score"] <= 100):
            failures.append(f"盘 {result['disk'].get('device_id')} 评分越界: {verdict_data['score']}")
        if verdict_data["level"] not in ("healthy", "warning", "danger"):
            failures.append(f"盘 {result['disk'].get('device_id')} 结论非法: {verdict_data['level']}")
        if not verdict_data["reasons"]:
            failures.append(f"盘 {result['disk'].get('device_id')} 理由为空")

    # 7) 报告生成（仅字符串，不写盘）
    html_text = report.build_report_html(results)
    print(f"\n[7] HTML 报告构建：{len(html_text)} 字符")
    if "硬盘健康卫士" not in html_text:
        failures.append("报告缺少标题")

    summary = verdict.summarize(results)
    print(f"\n[8] 汇总: {summary}")
    elapsed = time.perf_counter() - started
    print(f"\n=== 集成测试完成，耗时 {elapsed:.1f}s，{'通过' if not failures else '失败'} ===")
    if failures:
        for failure in failures:
            print(f"  [FAIL] {failure}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
