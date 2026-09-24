# -*- coding: utf-8 -*-
"""v1.2 真机验证脚本：NVMe 健康日志直读 + 卷映射备用通道。只读、不写盘。

用法（建议管理员）：
    python test/verify_v12_real_machine.py

期望（主理人真机参考值）：
- PhysicalDrive0：PowerOnHours ≈ 13296、PowerCycles ≈ 1072、累计写入 ≈ 8.6 TB；
- PhysicalDrive1（ZHITAI Ti600）：PowerOnHours ≈ 1556、PowerCycles ≈ 65、
  累计写入 ≈ 21.7 TB；
- 卷映射：C:/D: 的 dirty=False 且 disk_numbers 正确（D: 关联 0 和 1 两块盘）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import nvme_health, volume_check  # noqa: E402


def main() -> int:
    ok = True

    print("== NVMe 健康日志直读 ==")
    for n in (0, 1):
        health = nvme_health.query_nvme_health(n)
        print(f"-- PhysicalDrive{n} --")
        if health is None:
            print("   FAIL: query_nvme_health 返回 None（非管理员 / 非 NVMe / 查询失败）")
            ok = False
            continue
        written = nvme_health.format_data_units(health["data_units_written"])
        read = nvme_health.format_data_units(health["data_units_read"])
        print(f"   温度 {health['temperature_c']}°C  备用 {health['available_spare_pct']}%"
              f"（阈值 {health['spare_threshold']}%）  使用率 {health['percentage_used']}%")
        print(f"   通电 {health['power_on_hours']:,} 小时  通电次数 {health['power_cycles']:,}")
        print(f"   累计写入 {written}  累计读取 {read}")
        print(f"   不安全断电 {health['unsafe_shutdowns']:,}  媒体错误 {health['media_errors']:,}"
              f"  错误日志条目 {health['error_log_entries']:,}")
        if health["power_on_hours"] in (0, None):
            print("   FAIL: PowerOnHours 为 0/None（两种布局都未解析出数据）")
            ok = False

    print("\n== 卷映射（Get-Partition -> WMI 备用通道）==")
    volumes = volume_check.check_volumes()
    if not volumes:
        print("   FAIL: check_volumes 返回空列表")
        ok = False
    for volume in volumes:
        print(f"   {volume['drive']}  dirty={volume['dirty']}  "
              f"disk_number={volume.get('disk_number')}  disk_numbers={volume.get('disk_numbers')}")
    multi = [v for v in volumes if len(v.get("disk_numbers") or []) > 1]
    if multi:
        print(f"   跨盘卷：{[v['drive'] for v in multi]}")

    print("\n结果：" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
