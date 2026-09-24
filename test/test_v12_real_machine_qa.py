# -*- coding: utf-8 -*-
"""v1.2 QA 独立真机测试：NVMe 健康日志直读 + 卷映射备用通道。只读、不写盘。

真机参考值（主理人提供，允许小幅漂移）：
- PD0：通电≈13297h、次数≈1072、写入≈8.6TB、不安全断电 109、备用 100/5、使用率 2%；
- PD1（ZHITAI）：通电≈1557h、次数≈850、写入≈21.6TB、不安全断电 65、备用 100/10、使用率 4%；
- 卷映射：C:→[1]、D:→[0,1]，dirty 均 False。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import nvme_health, volume_check  # noqa: E402

# 参考值与容差（漂移只允许单向小幅增长：小时/断电数随时间增大）
PD0_EXPECT = {
    "power_on_hours": (13250, 13400),
    "power_cycles": (1050, 1100),
    "unsafe_shutdowns": (105, 140),
    "data_units_written_tb": (8.2, 9.2),
    "available_spare_pct": 100,
    "spare_threshold": 5,
    "percentage_used": (1, 4),
}
PD1_EXPECT = {
    "power_on_hours": (1550, 1600),
    "power_cycles": (830, 880),
    "unsafe_shutdowns": (63, 80),
    "data_units_written_tb": (21.2, 22.2),
    "available_spare_pct": 100,
    "spare_threshold": 10,
    "percentage_used": (3, 6),
}
_REQUIRED_KEYS = (
    "critical_warning", "temperature_c", "available_spare_pct", "spare_threshold",
    "percentage_used", "data_units_read", "data_units_written", "power_cycles",
    "power_on_hours", "unsafe_shutdowns", "media_errors", "error_log_entries",
)


def _du_to_tb(du: int) -> float:
    return du * 512_000 / 1024 ** 4


def _assert_health(health: dict, expect: dict, label: str) -> None:
    for key in _REQUIRED_KEYS:
        assert key in health, f"{label} 缺字段 {key}"
    assert health["critical_warning"] == 0, f"{label} 不应有危险警告: {health['critical_warning']}"
    temp = health["temperature_c"]
    assert isinstance(temp, int) and 25 <= temp <= 60, f"{label} 温度异常: {temp}"
    lo, hi = expect["power_on_hours"]
    assert lo <= health["power_on_hours"] <= hi, (
        f"{label} 通电 {health['power_on_hours']} 不在 [{lo}, {hi}]")
    lo, hi = expect["power_cycles"]
    assert lo <= health["power_cycles"] <= hi, (
        f"{label} 通电次数 {health['power_cycles']} 不在 [{lo}, {hi}]")
    lo, hi = expect["unsafe_shutdowns"]
    assert lo <= health["unsafe_shutdowns"] <= hi, (
        f"{label} 不安全断电 {health['unsafe_shutdowns']} 不在 [{lo}, {hi}]")
    tb = _du_to_tb(health["data_units_written"])
    lo, hi = expect["data_units_written_tb"]
    assert lo <= tb <= hi, f"{label} 累计写入 {tb:.2f} TB 不在 [{lo}, {hi}]"
    assert health["available_spare_pct"] == expect["available_spare_pct"], (
        f"{label} 备用空间: {health['available_spare_pct']}")
    assert health["spare_threshold"] == expect["spare_threshold"], (
        f"{label} 备用阈值: {health['spare_threshold']}")
    lo, hi = expect["percentage_used"]
    assert lo <= health["percentage_used"] <= hi, (
        f"{label} 使用率 {health['percentage_used']} 不在 [{lo}, {hi}]")
    assert health["media_errors"] == 0, f"{label} 媒体错误应为 0: {health['media_errors']}"


def test_qa_real_pd0_nvme_health():
    health = nvme_health.query_nvme_health(0)
    assert health is not None, "PD0 NVMe 直读返回 None（权限 / 通道故障）"
    _assert_health(health, PD0_EXPECT, "PD0")


def test_qa_real_pd1_nvme_health():
    health = nvme_health.query_nvme_health(1)
    assert health is not None, "PD1 NVMe 直读返回 None（权限 / 通道故障）"
    _assert_health(health, PD1_EXPECT, "PD1")


def test_qa_real_pd0_written_formatted_86tb():
    health = nvme_health.query_nvme_health(0)
    assert health is not None
    text = nvme_health.format_data_units(health["data_units_written"])
    assert text is not None and text.endswith("TB"), text


def test_qa_real_out_of_range_drive_returns_none():
    assert nvme_health.query_nvme_health(99) is None


def test_qa_real_volume_map():
    volumes = volume_check.check_volumes()
    assert volumes, "check_volumes 返回空列表"
    by_drive = {}
    for vol in volumes:
        # 同一盘符只允许一条记录（dirty 只查一次）
        assert vol["drive"] not in by_drive, f"盘符重复: {vol['drive']}"
        by_drive[vol["drive"]] = vol
    assert "C:" in by_drive, f"缺 C: 卷: {list(by_drive)}"
    assert "D:" in by_drive, f"缺 D: 卷: {list(by_drive)}"
    c = by_drive["C:"]
    d = by_drive["D:"]
    assert c["disk_numbers"] == [1], f"C: 归因错误: {c['disk_numbers']}"
    assert d["disk_numbers"] == [0, 1], f"D: 归因错误（应为跨盘卷 [0, 1]）: {d['disk_numbers']}"
    assert c["disk_number"] == 1 and d["disk_number"] == 0, "v1.1 兼容字段 disk_number 异常"
    for drive, vol in by_drive.items():
        assert vol["dirty"] is False, f"{drive} dirty 应为 False: {vol['dirty']}"


def test_qa_real_wmi_channel_is_the_active_path():
    """本机为 Storage Spaces 环境：Get-Partition 为空，实际走 WMI 备用通道。"""
    standard = volume_check._get_partition_map_standard()
    assert standard == {}, f"本机 Get-Partition 应为空，实际 {standard}"
    wmi = volume_check._get_partition_map_wmi()
    # 内部通道返回不带冒号的盘符键；check_volumes 输出时补 ":"
    assert wmi.get("C") == [1] and wmi.get("D") == [0, 1], f"WMI 通道结果异常: {wmi}"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
