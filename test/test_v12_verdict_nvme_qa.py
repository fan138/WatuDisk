# -*- coding: utf-8 -*-
"""v1.2 QA 独立测试：evaluate_disk NVMe 新规则边界 + nvme=None 时 v1.1 旧规则回归。

QA 自编用例与期望值（按 PRD 规则手工推算），不照抄工程师 selftest。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import verdict  # noqa: E402

_BASE_DISK = {
    "device_id": "0",
    "model": "QA Synthetic NVMe",
    "media_type": "SSD",
    "bus_type": "NVMe",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 1024 * 1024 ** 3,
    "serial": "QA0001",
}


def _good_nvme(**overrides) -> dict:
    base = {
        "critical_warning": 0, "temperature_c": 38, "available_spare_pct": 100,
        "spare_threshold": 10, "percentage_used": 4,
        "data_units_read": 36864460, "data_units_written": 46425974,
        "power_cycles": 850, "power_on_hours": 1557,
        "unsafe_shutdowns": 65, "media_errors": 0, "error_log_entries": 0,
    }
    base.update(overrides)
    return base


def _eval(nvme=None, counters=None, smart_attrs=None, events=0, dirty=None, disk=None):
    return verdict.evaluate_disk(
        disk or _BASE_DISK, counters, smart_attrs or [], events, [], dirty or [], nvme,
    )


# ---------------------------------------------------------------- healthy / critical_warning
def test_qa_nvme_good_healthy_full_score():
    v = _eval(nvme=_good_nvme())
    assert v["score"] == 100, v
    assert v["level"] == "healthy"
    assert v["level_text"] == "健康"


def test_qa_critical_warning_1_forces_danger_49():
    """critical_warning>0：扣 50 分 + force_danger 钳到 49。"""
    v = _eval(nvme=_good_nvme(critical_warning=1))
    assert v["score"] == 49, v
    assert v["level"] == "danger"
    assert any("危险警告" in r for r in v["reasons"]), v["reasons"]


def test_qa_critical_warning_0_no_deduct():
    v = _eval(nvme=_good_nvme(critical_warning=0))
    assert v["score"] == 100 and v["level"] == "healthy"


def test_qa_critical_and_low_spare_danger_wins():
    """critical_warning 与低备用同时出现：force_danger 优先于 force_warning。"""
    v = _eval(nvme=_good_nvme(critical_warning=1, available_spare_pct=5))
    assert v["level"] == "danger", v
    assert v["score"] == min(100 - 50 - 40, 49), v


# ---------------------------------------------------------------- 可用备用空间
def test_qa_spare_9_below_10_forces_warning():
    """备用 9 < 10：扣 40 + 至少警告档。"""
    v = _eval(nvme=_good_nvme(available_spare_pct=9))
    assert v["score"] == 60, v
    assert v["level"] == "warning", v
    assert any("备用空间" in r for r in v["reasons"]), v["reasons"]


def test_qa_spare_10_boundary_not_low():
    """备用 = 10（等于 10% 线且等于阈值）：不触发。"""
    v = _eval(nvme=_good_nvme(available_spare_pct=10, spare_threshold=10))
    assert v["score"] == 100 and v["level"] == "healthy", v


def test_qa_spare_below_threshold_triggers():
    """备用 20 < 阈值 30：虽 >=10% 仍触发（低于固件阈值是硬性风险）。"""
    v = _eval(nvme=_good_nvme(available_spare_pct=20, spare_threshold=30))
    assert v["level"] == "warning", v
    assert any("备用空间只剩 20%" in r for r in v["reasons"]), v["reasons"]


def test_qa_spare_reason_mentions_threshold():
    v = _eval(nvme=_good_nvme(available_spare_pct=5, spare_threshold=10))
    assert any("阈值 10%" in r for r in v["reasons"]), v["reasons"]


# ---------------------------------------------------------------- 媒体错误（每个 -8，封顶 24）
def test_qa_media_errors_1_deduct_8():
    v = _eval(nvme=_good_nvme(media_errors=1))
    assert v["score"] == 92, v
    assert any("媒体错误" in r for r in v["reasons"])


def test_qa_media_errors_3_deduct_24():
    v = _eval(nvme=_good_nvme(media_errors=3))
    assert v["score"] == 76, v


def test_qa_media_errors_5_capped_at_24():
    v = _eval(nvme=_good_nvme(media_errors=5))
    assert v["score"] == 76, v  # 8*5=40 -> 封顶 24


def test_qa_media_errors_huge_capped():
    v = _eval(nvme=_good_nvme(media_errors=100000))
    assert v["score"] == 76, v


def test_qa_media_errors_2_deduct_16():
    v = _eval(nvme=_good_nvme(media_errors=2))
    assert v["score"] == 84, v


# ---------------------------------------------------------------- 不安全断电（>100 扣 5）
def test_qa_unsafe_100_no_deduct():
    v = _eval(nvme=_good_nvme(unsafe_shutdowns=100))
    assert v["score"] == 100, v


def test_qa_unsafe_101_deduct_5():
    v = _eval(nvme=_good_nvme(unsafe_shutdowns=101))
    assert v["score"] == 95, v
    assert any("断电" in r for r in v["reasons"]), v["reasons"]


def test_qa_unsafe_65_real_machine_value_no_deduct():
    v = _eval(nvme=_good_nvme(unsafe_shutdowns=65))
    assert v["score"] == 100, v


# ---------------------------------------------------------------- 使用率（仅 Wear 无数据时扣）
def test_qa_pct_79_no_deduct():
    v = _eval(nvme=_good_nvme(percentage_used=79))
    assert v["score"] == 100, v


def test_qa_pct_80_deduct_15():
    v = _eval(nvme=_good_nvme(percentage_used=80))
    assert v["score"] == 85, v
    assert any("已使用寿命" in r for r in v["reasons"]), v["reasons"]


def test_qa_pct_89_deduct_15():
    v = _eval(nvme=_good_nvme(percentage_used=89))
    assert v["score"] == 85, v


def test_qa_pct_90_deduct_30():
    v = _eval(nvme=_good_nvme(percentage_used=90))
    assert v["score"] == 70, v
    assert any("已使用寿命" in r for r in v["reasons"]), v["reasons"]


def test_qa_pct_92_with_wear_no_double_deduct():
    """Wear 通道有值（5%）时 NVMe 使用率不得重复扣磨损分。"""
    v = _eval(nvme=_good_nvme(percentage_used=92), counters={"Temperature": 40, "Wear": 5})
    assert v["score"] == 100, v
    assert all("已使用寿命" not in r for r in v["reasons"]), v["reasons"]


def test_qa_pct_deduct_applies_on_non_ssd_skipped():
    """机械盘（非 SSD/NVMe 总线）不适用 NVMe 使用率规则。"""
    hdd = dict(_BASE_DISK, media_type="HDD", bus_type="SATA")
    v = _eval(nvme=_good_nvme(percentage_used=95), disk=hdd)
    assert v["score"] == 100, v


# ---------------------------------------------------------------- nvme=None：v1.1 旧规则回归
def test_qa_none_nvme_healthy_with_counters():
    v = _eval(counters={"Temperature": 40, "Wear": 5, "PowerOnHours": 9000})
    assert v["score"] == 100 and v["level"] == "healthy"
    # 有数据通道时不出现「数据受限」提示
    assert all("无法读取" not in r for r in v["reasons"]), v["reasons"]


def test_qa_none_nvme_limited_data_note():
    """三通道全空：保留 v1.1 的数据受限提示。"""
    v = _eval()
    assert any("无法读取" in r and "管理员" in r for r in v["reasons"]), v["reasons"]


def test_qa_none_nvme_unhealthy_forces_danger():
    v = _eval(counters={"Temperature": 40}, disk=dict(_BASE_DISK, health_status="Unhealthy"))
    assert v["score"] == 49 and v["level"] == "danger", v


def test_qa_none_nvme_warning_health_status_deduct_15():
    v = _eval(counters={"Temperature": 40}, disk=dict(_BASE_DISK, health_status="Warning"))
    assert v["score"] == 85 and v["level"] == "healthy", v


def test_qa_none_nvme_c5_forces_warning():
    """v1.1 C5 待映射扇区：扣 20+ 且 force_warning（80 分被钳到 79）。"""
    smart = [{"id": 0xC5, "name": "待映射扇区数", "value": 100, "raw": 1}]
    v = _eval(smart_attrs=smart)
    assert v["score"] == 79 and v["level"] == "warning", v


def test_qa_none_nvme_c6_danger():
    smart = [{"id": 0xC6, "name": "无法修正扇区数", "value": 100, "raw": 2}]
    v = _eval(smart_attrs=smart)
    assert v["score"] == 55 and v["level"] == "warning", v  # 45 扣分 -> 55


def test_qa_none_nvme_temperature_boundaries():
    v60 = _eval(counters={"Temperature": 60})
    assert v60["score"] == 92, v60
    v59 = _eval(counters={"Temperature": 59})
    assert v59["score"] == 100, v59
    v70 = _eval(counters={"Temperature": 70})
    assert v70["score"] == 85, v70


def test_qa_none_nvme_dirty_volume_deduct_40():
    v = _eval(dirty=[{"drive": "C:", "dirty": True, "disk_number": 0}])
    assert v["score"] == 60 and v["level"] == "warning", v
    assert any("损坏位" in r for r in v["reasons"]), v["reasons"]


def test_qa_none_nvme_event_count_deduct():
    v25 = _eval(events=25)
    assert v25["score"] == 60 and v25["level"] == "warning", v25
    v3 = _eval(events=3)
    assert v3["score"] == 85, v3
    v1 = _eval(events=1)
    assert v1["score"] == 92, v1
    v0 = _eval(events=0)
    assert v0["score"] == 100, v0


def test_qa_nvme_present_no_limited_note_even_without_counters():
    """有 NVMe 健康数据时不提示数据受限（v1.2 规则）。"""
    v = _eval(nvme=_good_nvme())
    assert all("无法读取" not in r for r in v["reasons"]), v["reasons"]


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
