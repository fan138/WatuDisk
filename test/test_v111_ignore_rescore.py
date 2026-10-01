# -*- coding: utf-8 -*-
"""v1.1.1 QA 独立测试：忽略项不再扣分（评分回归剩余项）+ 颜色警示保留语义。

用户定稿（2026-10-01）：「当我点击忽略后，我希望评分依然回归到 100 分。
但依然做颜色警示，仅仅是自我安慰而已。」

覆盖点：
- verdict.evaluate_disk(ignored_keys=...) 各扣分块与指标 key 的映射；
- 被忽略后 force_warning / force_danger 钳制同步解除（评分才能真正回 100）；
- 理由中如实注明「已忽略」（不掩盖被忽略的事实）；
- 未忽略时行为与旧版完全一致（回归保障）；
- store.ignored_keys_for 按序列号过滤；
- metric_items_for_result 产出的 key 与评分引擎映射一一对应（防错位）。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import metrics, verdict  # noqa: E402
from core.store import Store  # noqa: E402

_BASE_DISK = {
    "device_id": "0",
    "model": "QA Synthetic SATA SSD",
    "media_type": "SSD",
    "bus_type": "SATA",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 512 * 1024 ** 3,
    "serial": "QAIGNORE0001",
}
_GOOD_COUNTERS = {"Temperature": 38, "Wear": 3, "PowerOnHours": 9000}


def _mk_attr(attr_id: int, raw: int) -> dict:
    return {"id": attr_id, "hex": f"0x{attr_id:02X}", "name": "", "value": 100, "raw": raw}


def _sata_with(attr_id: int, raw: int) -> dict:
    return verdict.evaluate_disk(
        _BASE_DISK, _GOOD_COUNTERS, [_mk_attr(attr_id, raw)], 0, [], [],
    )


def _sata_ignored(attr_id: int, raw: int, ignored: set[str]) -> dict:
    return verdict.evaluate_disk(
        _BASE_DISK, _GOOD_COUNTERS, [_mk_attr(attr_id, raw)], 0, [], [],
        ignored_keys=ignored,
    )


# ---------------------------------------------------------------- SATA SMART
def test_c5_unignored_still_deducts():
    """未忽略 C5：维持旧行为——扣分 + 至少警告档（force_warning）。"""
    v = _sata_with(0xC5, 8)
    assert v["score"] < 100, v
    assert v["level"] == verdict.LEVEL_WARNING, v


def test_c5_ignored_returns_to_100():
    """忽略 pending_sector：C5 不再扣分，评分回归 100，钳制同步解除。"""
    v = _sata_ignored(0xC5, 8, {"pending_sector"})
    assert v["score"] == 100, v
    assert v["level"] == verdict.LEVEL_HEALTHY, v
    assert any("忽略" in r and "待映射扇区" in r for r in v["reasons"]), v["reasons"]


def test_c6_ignored_returns_to_100():
    """忽略 uncorrectable：C6 不再扣分，评分回归 100。"""
    v = _sata_ignored(0xC6, 88, {"uncorrectable"})
    assert v["score"] == 100, v
    assert v["level"] == verdict.LEVEL_HEALTHY, v


def test_05_and_c7_ignored():
    """忽略 reallocated / crc_errors：各自独立生效。"""
    assert _sata_ignored(0x05, 5000, {"reallocated"})["score"] == 100
    assert _sata_ignored(0xC7, 99999, {"crc_errors"})["score"] == 100


def test_partial_ignore_keeps_other_deductions():
    """只忽略 C5，C6 仍照常扣分——忽略只作用于对应项。"""
    v = verdict.evaluate_disk(
        _BASE_DISK, _GOOD_COUNTERS,
        [_mk_attr(0xC5, 8), _mk_attr(0xC6, 10)], 0, [], [],
        ignored_keys={"pending_sector"},
    )
    assert v["score"] < 100, v
    assert any("无法修正" in r for r in v["reasons"]), v["reasons"]


# ---------------------------------------------------------------- counters 通道
def test_temp_ignored():
    """忽略 current_temp：高温不再扣分。"""
    counters = dict(_GOOD_COUNTERS, Temperature=72)
    v = verdict.evaluate_disk(_BASE_DISK, counters, [], 0, [], [], ignored_keys={"current_temp"})
    assert v["score"] == 100, v


def test_wear_ignored():
    """忽略 life_remaining：SSD 磨损不再扣分。"""
    counters = dict(_GOOD_COUNTERS, Wear=95)
    v = verdict.evaluate_disk(
        dict(_BASE_DISK, media_type="SSD"), counters, [], 0, [], [],
        ignored_keys={"life_remaining"},
    )
    assert v["score"] == 100, v


def test_read_errors_ignored():
    """忽略 uncorrected_read：读取错误不再扣分（写入通道不受影响）。"""
    counters = dict(_GOOD_COUNTERS, ReadErrorsUncorrected=120, WriteErrorsUncorrected=60)
    v = verdict.evaluate_disk(_BASE_DISK, counters, [], 0, [], [], ignored_keys={"uncorrected_read"})
    assert v["score"] < 100, v
    assert not any(r.startswith("累计出现") and "读取" in r for r in v["reasons"]), v["reasons"]
    assert any("忽略" in r and "不可修正读取错误" in r for r in v["reasons"]), v["reasons"]
    v2 = verdict.evaluate_disk(
        _BASE_DISK, counters, [], 0, [], [],
        ignored_keys={"uncorrected_read", "uncorrected_write"},
    )
    assert v2["score"] == 100, v2


# ---------------------------------------------------------------- NVMe 通道
_NVME_BASE = {
    "critical_warning": 0, "temperature_c": 40, "available_spare_pct": 100,
    "spare_threshold": 10, "media_errors": 0, "unsafe_shutdowns": 5,
    "percentage_used": 3, "power_on_hours": 9000, "power_cycles": 500,
    "data_units_written": 10_000_000, "data_units_read": 20_000_000,
}


def test_nvme_spare_ignored_releases_force_warning():
    """忽略 spare：NVMe 备用空间低不再扣分，force_warning 一并解除。"""
    nvme = dict(_NVME_BASE, available_spare_pct=5)
    v = verdict.evaluate_disk(_BASE_DISK, None, [], 0, [], [], nvme, ignored_keys={"spare"})
    assert v["score"] == 100, v
    assert v["level"] == verdict.LEVEL_HEALTHY, v


def test_nvme_media_errors_ignored():
    """忽略 media_errors：NVMe 媒体错误不再扣分。"""
    nvme = dict(_NVME_BASE, media_errors=5)
    v = verdict.evaluate_disk(_BASE_DISK, None, [], 0, [], [], nvme, ignored_keys={"media_errors"})
    assert v["score"] == 100, v


def test_nvme_pct_used_ignored():
    """忽略 pct_used：NVMe 使用率不再扣分。"""
    nvme = dict(_NVME_BASE, percentage_used=92)
    v = verdict.evaluate_disk(
        dict(_BASE_DISK, bus_type="NVMe"), None, [], 0, [], [], nvme,
        ignored_keys={"pct_used"},
    )
    assert v["score"] == 100, v


def test_nvme_critical_warning_cannot_be_ignored():
    """NVMe 危险警告没有可点击的指标行，不提供忽略（安全兜底）。"""
    nvme = dict(_NVME_BASE, critical_warning=1)
    v = verdict.evaluate_disk(_BASE_DISK, None, [], 0, [], [], nvme, ignored_keys={"critical_warning"})
    assert v["level"] == verdict.LEVEL_DANGER, v


# ---------------------------------------------------------------- 事件 / 汇总
def test_event_count_ignored():
    """忽略 event_count：事件日志不再扣分。"""
    v = verdict.evaluate_disk(_BASE_DISK, _GOOD_COUNTERS, [], 25, [], [], ignored_keys={"event_count"})
    assert v["score"] == 100, v


def test_ignored_only_reasons_note_present():
    """全部扣分项被忽略时：理由含忽略注明，且无「各项正常」的误导句。"""
    v = _sata_ignored(0xC5, 8, {"pending_sector"})
    assert any("忽略" in r for r in v["reasons"]), v["reasons"]
    assert not any("均在正常范围内" in r for r in v["reasons"]), v["reasons"]


# ---------------------------------------------------------------- key 对齐
def test_metric_keys_covered_by_verdict_mapping():
    """metric_items_for_result 产出的可忽略警示 key 必须都在评分映射内。

    映射清单（verdict.evaluate_disk 内的忽略判断）——新增警示阈值时须同步。
    """
    covered = {
        "current_temp", "max_temp", "life_remaining", "pct_used", "spare",
        "media_errors", "critical_warning", "unsafe_shutdowns",
        "uncorrected_read", "uncorrected_write", "reallocated",
        "pending_sector", "uncorrectable", "crc_errors", "event_count",
    }
    # 用一份"全坏"样本展开指标，断言所有 level>=CAUTION 的 key 都在映射里
    counters = dict(_GOOD_COUNTERS, Temperature=72, Wear=95,
                    ReadErrorsUncorrected=120, WriteErrorsUncorrected=60)
    attrs = [_mk_attr(0x05, 5000), _mk_attr(0xC5, 8), _mk_attr(0xC6, 10), _mk_attr(0xC7, 999)]
    result = {
        "disk": _BASE_DISK, "counters": counters, "smart_attrs": attrs,
        "nvme_health": dict(_NVME_BASE, media_errors=3, percentage_used=92,
                            available_spare_pct=5),
        "event_count": 25, "event_recent": [], "dirty_volumes": [], "all_volumes": [],
    }
    items = metrics.metric_items_for_result(result)
    alarming = {item["key"] for item in items if item["level"] >= metrics.LEVEL_CAUTION}
    unexpected = alarming - covered
    assert not unexpected, f"指标 key 未接入评分忽略映射: {unexpected}"


# ---------------------------------------------------------------- store
def test_store_ignored_keys_for_filters_by_serial():
    """ignored_keys_for 只返回该序列号的忽略项。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(dir_override=tmp)
        store.set_ignored(store.ignore_key("SER_A", "pending_sector"), True)
        store.set_ignored(store.ignore_key("SER_A", "current_temp"), True)
        store.set_ignored(store.ignore_key("SER_B", "pending_sector"), True)
        assert store.ignored_keys_for("SER_A") == {"pending_sector", "current_temp"}
        assert store.ignored_keys_for("SER_B") == {"pending_sector"}
        assert store.ignored_keys_for("SER_C") == set()
        store.set_ignored(store.ignore_key("SER_A", "pending_sector"), False)
        assert store.ignored_keys_for("SER_A") == {"current_temp"}


def test_no_ignored_keys_matches_legacy_behavior():
    """不传 ignored_keys（旧调用方式）结果与传空集合完全一致——回归保障。"""
    legacy = _sata_with(0xC5, 8)
    explicit = verdict.evaluate_disk(
        _BASE_DISK, _GOOD_COUNTERS, [_mk_attr(0xC5, 8)], 0, [], [], ignored_keys=set(),
    )
    assert legacy["score"] == explicit["score"]
    assert legacy["level"] == explicit["level"]


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
