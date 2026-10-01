# -*- coding: utf-8 -*-
"""v1.1.0 QA 独立测试：USB 无 SMART 设备的诚实展示 + SMART 字典扩充。

背景（52pojie 论坛反馈）：
- 「检测不到优盘」——U 盘普遍不提供 SMART，挖兔此前显示误导性满分；
  v1.1.0 起如实标注「不支持」。
- 「数据不怎么准确」——SMART 属性名字典仅 21 项，大量厂商属性显示
  「未知属性 0xXX」；v1.1.0 扩充至 70+ 项（ATA 规范 + CDI/smartmontools 通行约定）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import verdict  # noqa: E402
from core.smart_parser import ATTR_NAMES, attr_display_name  # noqa: E402

_BASE_DISK = {
    "device_id": "0",
    "model": "QA Synthetic USB Stick",
    "media_type": "Unspecified",
    "bus_type": "USB",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 32 * 1024 ** 3,
    "serial": "QAUSB0001",
}


def _eval_usb_no_data() -> dict:
    return verdict.evaluate_disk(_BASE_DISK, None, [], 0, [], [], None)


# ---------------------------------------------------------------- USB 无数据
def test_qa_usb_no_data_marks_unsupported():
    """USB 盘且全部健康通道无数据：monitor_supported=False + 对症文案。"""
    v = _eval_usb_no_data()
    assert v["monitor_supported"] is False, v
    assert v["score"] == 100, v
    assert any("USB 设备" in r and "SMART" in r for r in v["reasons"]), v["reasons"]


def test_qa_usb_no_data_no_admin_hint():
    """USB 盘无数据时不得再提示「未以管理员身份运行」（文案对症）。"""
    v = _eval_usb_no_data()
    assert not any("管理员" in r for r in v["reasons"]), v["reasons"]


def test_qa_sata_no_data_keeps_admin_hint():
    """非 USB 盘无数据时保留原有「权限/系统不支持」提示，且 monitor_supported=True。"""
    disk = dict(_BASE_DISK, bus_type="SATA", media_type="SSD")
    v = verdict.evaluate_disk(disk, None, [], 0, [], [], None)
    assert v["monitor_supported"] is True, v
    assert any("管理员" in r for r in v["reasons"]), v["reasons"]


def test_qa_usb_with_counters_still_supported():
    """USB 盘但计数器通道有数据：不算「不支持」。"""
    counters = {"Temperature": 30, "PowerOnHours": 1200, "Wear": 3}
    v = verdict.evaluate_disk(_BASE_DISK, counters, [], 0, [], [], None)
    assert v["monitor_supported"] is True, v


def test_qa_supported_flag_true_by_default():
    """常规 NVMe 盘：monitor_supported 恒为 True（向后兼容）。"""
    disk = dict(_BASE_DISK, bus_type="NVMe", media_type="SSD")
    v = verdict.evaluate_disk(disk, None, [], 0, [], [], None)
    assert v["monitor_supported"] is True, v


# ---------------------------------------------------------------- summarize 排除
def test_qa_summarize_excludes_unsupported():
    """不支持监测的设备不计入健康/警告/危险统计，但计入总数。"""
    usb = {"verdict": _eval_usb_no_data()}
    sata_ok = {
        "verdict": verdict.evaluate_disk(
            dict(_BASE_DISK, bus_type="SATA"), {"Temperature": 30}, [], 0, [], [], None
        )
    }
    counts = verdict.summarize([usb, sata_ok])
    assert counts["total"] == 2, counts
    assert counts["healthy"] == 1, counts
    assert counts["warning"] == 0, counts
    assert counts["danger"] == 0, counts


# ---------------------------------------------------------------- 字典扩充
def test_qa_attr_dict_expanded():
    """v1.1.0 字典扩充：至少 60 项，关键新属性可查。"""
    assert len(ATTR_NAMES) >= 60, len(ATTR_NAMES)
    for attr_id in (0x0A, 0xBB, 0xBC, 0xBD, 0xBE, 0xC4, 0xDD, 0xE1, 0xEA, 0xF9, 0xAE):
        assert attr_id in ATTR_NAMES, f"0x{attr_id:02X} 应在字典中"


def test_qa_attr_dict_keeps_existing_names():
    """既有断言不回归：0xC5 名称不变，未知属性仍返回占位名。"""
    assert attr_display_name(0xC5) == "待映射扇区数"
    assert attr_display_name(0x99).startswith("未知属性")
    assert attr_display_name(0xBE) == "气流温度"


def test_qa_attr_dict_micron_ca_not_misleading():
    """0xCA 在 Micron 盘上是「已用寿命百分比」，不得再标为「SSD 剩余寿命」。"""
    assert "剩余寿命" not in ATTR_NAMES[0xCA], ATTR_NAMES[0xCA]
    assert "厂商" in ATTR_NAMES[0xCA], ATTR_NAMES[0xCA]


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
