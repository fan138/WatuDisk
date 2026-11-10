# -*- coding: utf-8 -*-
"""v1.2.3 回归测试：SATA 固态剩余寿命漏读修复（#20 续）。

根因：v1.2.2 的 resolve_wear_used 对 SATA 固态只认 Windows StorageReliabilityCounter.Wear，
而西数 / SanDisk 等盘的 Wear 常为空/0，真实剩余寿命写在 SMART 属性（0xE7 等）。
本文件守护 v1.2.3 的兜底解析：
- SATA 固态 Windows 侧无可靠磨损时，回退读 SMART 0xE7（兜底 0xE9 / 0xE8）归一化值；
- 不破坏 NVMe 直读、Windows 真实 Wear、HDD 等既有路径；
- 判读层 / 指标表 / 界面摘要三处共用同一个解析入口（口径一致）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

import core.metrics as metrics  # noqa: E402
import core.verdict as verdict  # noqa: E402
from core.verdict import resolve_wear_used  # noqa: E402

_SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
VERDICT_SRC = open(os.path.join(_SRC_DIR, "core", "verdict.py"), encoding="utf-8").read()
METRICS_SRC = open(os.path.join(_SRC_DIR, "core", "metrics.py"), encoding="utf-8").read()
UI_SRC = open(os.path.join(_SRC_DIR, "ui", "main_window.py"), encoding="utf-8").read()


def _sata_ssd(**over):
    d = {"media_type": "SSD", "bus_type": "SATA", "device_id": "0", "health_status": "Healthy"}
    d.update(over)
    return d


# ---------------- resolve_wear_used 单元测试 ----------------

def test_nvme_uses_direct_read():
    assert resolve_wear_used(_sata_ssd(bus_type="NVME"), None, {"percentage_used": 40}) == 40


def test_nvme_unreported_is_none():
    assert resolve_wear_used(_sata_ssd(bus_type="NVME"), None, {"percentage_used": 255}) is None


def test_sata_smart_e7_fallback():
    # Windows 无 Wear，SMART 0xE7=60（剩余 60%）→ 已消耗 40
    assert resolve_wear_used(_sata_ssd(), {"Wear": None}, None, {0xE7: 60}) == 40


def test_sata_wear0_highpower_falls_to_smart():
    # 通电 5 万小时却 Wear=0（Windows 默认值）→ 回退 SMART
    assert resolve_wear_used(_sata_ssd(), {"Wear": 0, "PowerOnHours": 50000}, None, {0xE7: 60}) == 40


def test_sata_genuinely_new_keeps_zero():
    # 通电仅 500 小时、Wear=0 → 真全新，不覆盖为 SMART 值
    assert resolve_wear_used(_sata_ssd(), {"Wear": 0, "PowerOnHours": 500}, None, {0xE7: 100}) == 0


def test_sata_no_smart_no_wear_is_none():
    # 既无 Windows Wear 也无 SMART → 无数据（界面显示「未提供」）
    assert resolve_wear_used(_sata_ssd(), {"Wear": None}, None, {}) is None


def test_sata_e7_out_of_range_rejected():
    # 0xE7=255 越界 → 不当寿命
    assert resolve_wear_used(_sata_ssd(), {"Wear": None}, None, {0xE7: 255}) is None


def test_sata_e9_fallback():
    assert resolve_wear_used(_sata_ssd(), {"Wear": None}, None, {0xE9: 60}) == 40


def test_sata_e8_fallback():
    assert resolve_wear_used(_sata_ssd(), {"Wear": None}, None, {0xE8: 50}) == 50


def test_hdd_always_none():
    assert resolve_wear_used({"media_type": "HDD", "bus_type": "SCSI"}, {"Wear": 30}, None, {0xE7: 60}) is None


def test_sata_windows_real_wear_preferred():
    # Windows 给出了真实 Wear=40，即使 SMART 不同也以 Windows 为准
    assert resolve_wear_used(_sata_ssd(), {"Wear": 40}, None, {0xE7: 60}) == 40


def test_backward_compat_three_args():
    # 旧调用方式（不传 smart_values）对 SATA 无 Wear 仍返回 None
    assert resolve_wear_used(_sata_ssd(), {"Wear": None}, None) is None


# ---------------- 集成测试：指标表 ----------------

def test_metrics_shows_sata_smart_life():
    result = {
        "disk": _sata_ssd(),
        "counters": None,
        "smart_attrs": [{"id": 0xE7, "hex": "0xE7", "name": "SSD 剩余寿命",
                         "value": 60, "raw": 0}],
        "nvme_health": None,
    }
    items = {it["key"]: it for it in metrics.metric_items_for_result(result)}
    assert items["life_remaining"]["text"] == "60%", items["life_remaining"]


def test_metrics_no_life_row_hidden():
    # 既无 Windows Wear 也无 SMART → 寿命行整行隐藏（不显示任何误导值，比「—」更干净）
    result = {"disk": _sata_ssd(), "counters": None, "smart_attrs": [], "nvme_health": None}
    items = {it["key"]: it for it in metrics.metric_items_for_result(result)}
    assert "life_remaining" not in items


# ---------------- 集成测试：判读层 ----------------

def test_verdict_deducts_on_low_sata_life():
    # 0xE7=30（剩余 30%，已消耗 70%）→ 应扣寿命分并给出剩余寿命理由
    disk = _sata_ssd()
    smart = [{"id": 0xE7, "hex": "0xE7", "name": "SSD 剩余寿命", "value": 30, "raw": 0}]
    res = verdict.evaluate_disk(disk, None, smart, 0, [], [], None, set())
    assert any("剩余寿命约 30%" in r for r in res["reasons"]), res["reasons"]


def test_verdict_unprovided_on_no_data():
    disk = _sata_ssd()
    res = verdict.evaluate_disk(disk, None, [], 0, [], [], None, set())
    assert any("未提供" in r for r in res["reasons"]), res["reasons"]


# ---------------- 源码守卫：三处调用口径一致 ----------------

def test_call_sites_pass_smart_values():
    assert "resolve_wear_used(disk, counters, nvme_health, smart_values)" in VERDICT_SRC
    assert "resolve_wear_used(disk, counters, nvme, smart_values)" in METRICS_SRC
    assert "_sv = {" in UI_SRC and 'resolve_wear_used(disk, counters, result.get("nvme_health"), _sv)' in UI_SRC


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
