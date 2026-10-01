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

from core import metrics, verdict  # noqa: E402
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


def test_qa_vendor_private_range_named_not_unknown():
    """v1.1.2：0xA0-0xA9 与 0xF5 是厂商私有区段，标「厂商私有属性」而非「未知属性」。

    来源：HYN2TB 实测报告出现 10 个「未知属性 0xA0-0xA9/0xF5」；
    ATA 规范中该区段本就是厂商私有，统一诚实标注、不猜测具体含义。
    """
    for attr_id in (0xA0, 0xA3, 0xA5, 0xA9, 0xF5):
        name = attr_display_name(attr_id)
        assert "厂商私有" in name, (attr_id, name)
        assert "未知" not in name, (attr_id, name)
    # 真正的未知属性（区段之外）仍回退「未知属性 0xXX」
    assert attr_display_name(0x99).startswith("未知属性")
    assert attr_display_name(0x13).startswith("未知属性")


# ---------------------------------------------------------------- v1.1.1 SATA 兜底填格
def _sata_hyn_result() -> dict:
    """还原 52pojie 坛友 HYN2TB（SATA SSD，系统计数器大面积缺项）的实测形态。"""
    return {
        "disk": {"device_id": "1", "model": "HYN2TB", "media_type": "SSD",
                 "bus_type": "SATA", "health_status": "Healthy", "op_status": "OK",
                 "size": 1953514584 * 512, "serial": "RNG000000000000000080"},
        "counters": {},
        "smart_attrs": [
            {"id": 0x09, "name": "通电时间", "value": 100, "raw": 13184},
            {"id": 0x0C, "name": "通电次数", "value": 100, "raw": 631},
            {"id": 0xC0, "name": "意外断电缩回次数", "value": 100, "raw": 57},
            {"id": 0xC2, "name": "温度", "value": 100, "raw": 40},
            {"id": 0xE8, "name": "剩余寿命 / 可用备用空间（厂商相关）", "value": 100, "raw": 100},
            {"id": 0xF1, "name": "累计写入量（LBA）", "value": 100, "raw": 592464},
            {"id": 0xF2, "name": "累计读取量（LBA）", "value": 100, "raw": 803886},
        ],
        "event_count": 0,
        "event_recent": [],
        "dirty_volumes": [],
        "all_volumes": [],
        "verdict": {"score": 100, "level": "healthy", "level_text": "健康", "reasons": []},
    }


def test_qa_sata_fallback_fills_from_smart():
    """counters 缺项时从 SMART 兜底：备用空间/断电次数/温度/读写量。"""
    items = {item["label"]: item["text"] for item in metrics.metric_items_for_result(_sata_hyn_result())}
    assert items["可用备用空间"] == "100%", items
    assert items["不安全断电次数"] == "57", items
    assert items["当前温度"] == "40°C", items
    assert items["通电时间"] == "13,184 小时 · 约 1.5 年", items
    assert items["累计写入量"] == "592,464（厂商单位）", items
    assert items["累计读取量"] == "803,886（厂商单位）", items


def test_qa_sata_fallback_hides_unavailable_rows():
    """真没有数据源的行整行隐藏，不再显示「—」。"""
    items = {item["label"]: item["text"] for item in metrics.metric_items_for_result(_sata_hyn_result())}
    for hidden in ("加载/卸载循环", "主轴启停次数", "历史最高温度",
                   "不可修正读取错误", "不可修正写入错误",
                   "累计读取错误", "累计写入错误", "媒体错误数"):
        assert hidden not in items, f"{hidden} 无数据源应隐藏"


def test_qa_lba_plausible_still_converts():
    """0xF1 原始值按 LBA 换算 ≥1GB 时正常转容量，不标厂商单位。"""
    result = _sata_hyn_result()
    result["smart_attrs"] = [{"id": 0xF1, "name": "累计写入量（LBA）", "value": 100, "raw": 20_000_000_000}]
    items = {item["label"]: item["text"] for item in metrics.metric_items_for_result(result)}
    assert items["累计写入量"] == "9.31 TB", items  # 1024 进制：2e10×512B ≈ 9.31 TiB


# ---------------------------------------------------------------- v1.1.1 NVMe 危险警告位分解
def test_qa_nvme_critical_warning_named_bits():
    """v1.1.1：NVMe 危险警告按规范位分解成具名项（参考硬件狗狗五项设备状态）。"""
    nvme = {
        "critical_warning": 9,  # bit0 备用空间不足 + bit3 只读模式
        "temperature_c": 38, "available_spare_pct": 100,
        "spare_threshold": 10, "percentage_used": 4, "power_cycles": 850,
        "power_on_hours": 1557, "unsafe_shutdowns": 65, "media_errors": 0,
    }
    disk = dict(_BASE_DISK, bus_type="NVMe", media_type="SSD")
    v = verdict.evaluate_disk(disk, None, [], 0, [], [], nvme)
    assert v["level"] == "danger", v
    joined = " ".join(v["reasons"])
    assert "备用空间已低于阈值" in joined, joined
    assert "只读保护模式" in joined, joined


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
