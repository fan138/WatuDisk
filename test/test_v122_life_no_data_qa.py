# -*- coding: utf-8 -*-
"""v1.2.2（#20）SSD 寿命「假数据」双向校验的回归测试。

坛友反馈场景（dddd592，金士顿 SA400）：通电 43,393 小时、累计写入约 64TB，
金士顿官方 SSD Manager 与 CrystalDiskInfo 均显示剩余寿命 54%，挖兔却显示
「寿命剩余 100%」——健康分 100 没错（三方都判健康），错的是寿命这个数字。

根因：金士顿这块盘不通过标准 SMART 报告磨损，Windows 的
Get-StorageReliabilityCounter 拿不到真实值时会填回 **Wear=0**；旧版照单全收，
100-0=100% → 显示成全新。与 v1.2.0 防过的 Wear=100（假耗尽，SV300 案）
相对，这是「假全新」的一面——**默认值语义的字段，两端都不可信**。

修复口径（三层统一，共用 verdict.resolve_wear_used）：
- verdict  ：Wear=0 且通电 ≥10,000 小时 → 判「未提供寿命数据」，不出寿命结论；
             NVMe 优先采信健康日志直读的 percentage_used，255（规范规定的
             「未上报」值）同样判无数据；
- metrics  ：指标表显示「未提供」，绝不给误导性百分比；
- 界面     ：卡片摘要行显示「寿命未提供」。

反向保护：Wear=0 但通电很短的准新盘仍按 100% 显示；Wear=95 等非默认值
照真实测量采信；Wear=100 防线（v1.2.0）不回归。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import metrics as metrics_mod  # noqa: E402
from core import report as report_mod  # noqa: E402
from core import verdict  # noqa: E402

UI_PATH = os.path.join(
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")),
    "ui",
    "main_window.py",
)
with open(UI_PATH, "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()

# 坛友实机：KINGSTON SA400S37480G，SATA / SSD / 480GB，通电 43,393 小时
SA400 = {
    "device_id": "1",
    "model": "KINGSTON SA400S37480G",
    "media_type": "SSD",
    "bus_type": "SATA",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 480 * 1024 ** 3,
    "serial": "50026B72720B9C6B",
}

# 该盘 SMART 明细：无任何寿命属性（官方工具走厂商专有通道才拿得到 54%）
SA400_SMART_ATTRS = [
    {"id": 0x09, "hex": "0x09", "name": "通电时间", "value": 1, "raw": 43393},
    {"id": 0x0C, "hex": "0x0C", "name": "通电次数", "value": 95, "raw": 2187},
    {"id": 0xC2, "hex": "0xC2", "name": "温度", "value": 118, "raw": 38},
    {"id": 0xBB, "hex": "0xBB", "name": "报告的不正确无法纠正的错误", "value": 100, "raw": 0},
]

# Windows 拿不到真实磨损时填回的默认 Wear=0（本案元凶）
FAKE_ZERO_COUNTERS = {
    "Temperature": 38,
    "Wear": 0,
    "PowerOnHours": 43393,
    "ReadErrorsUncorrected": 0,
    "WriteErrorsUncorrected": 0,
}

# NVMe 盘：直读健康日志有真实使用率，Windows 计数器却是 0（不同步）
NVME_DISK = dict(SA400, model="Samsung SSD 980 PRO 1TB", bus_type="NVME", media_type="SSD")
NVME_COUNTERS = {"Temperature": 45, "Wear": 0, "PowerOnHours": 8600}
NVME_HEALTH = {"percentage_used": 46, "temperature_c": 45, "media_errors": 0}


def _metric_row(result: dict, key: str) -> dict | None:
    for item in metrics_mod.metric_items_for_result(result):
        if item.get("key") == key:
            return item
    return None


# ---------------- resolve_wear_used 解析层 ----------------

def test_sa400_wear_zero_with_high_hours_is_no_data():
    """核心断言：Wear=0 且通电 4.3 万小时 → 无可靠寿命数据（SA400 案）。"""
    wear = verdict.resolve_wear_used(SA400, FAKE_ZERO_COUNTERS, None)
    assert wear is None, f"Wear=0+高通电应判无数据，实际={wear}"


def test_wear_zero_new_drive_still_shows_full():
    """反向保护：Wear=0 但通电很短的准新盘仍按 0% 磨损显示（100% 剩余）。"""
    wear = verdict.resolve_wear_used(SA400, dict(FAKE_ZERO_COUNTERS, PowerOnHours=500), None)
    assert wear == 0, f"准新盘 Wear=0 应采信，实际={wear}"


def test_wear_zero_without_hours_is_kept():
    """边界：Wear=0 但无通电时间可校验时，维持原值（不冤枉也不放过）。"""
    wear = verdict.resolve_wear_used(SA400, {"Wear": 0}, None)
    assert wear == 0, f"无通电数据时应原样返回 0，实际={wear}"


def test_nvme_prefers_direct_read_over_counter():
    """NVMe 优先直读 percentage_used——比 Windows 转手的计数器可信。"""
    wear = verdict.resolve_wear_used(NVME_DISK, NVME_COUNTERS, NVME_HEALTH)
    assert wear == 46, f"应取直读值 46，实际={wear}"


def test_nvme_pct_255_is_no_data():
    """NVMe 规范：Percentage Used = 255 表示未上报 → 判无数据。"""
    wear = verdict.resolve_wear_used(NVME_DISK, NVME_COUNTERS, dict(NVME_HEALTH, percentage_used=255))
    assert wear is None, f"255 应判无数据，实际={wear}"


def test_hdd_returns_none():
    """机械盘不适用寿命概念。"""
    hdd = dict(SA400, media_type="HDD", bus_type="SATA")
    assert verdict.resolve_wear_used(hdd, FAKE_ZERO_COUNTERS, None) is None


# ---------------- verdict 判读层 ----------------

def test_sa400_not_shown_as_full_life():
    """核心断言：这块盘不应再出现「寿命剩余 100%」这类误导结论。"""
    v = verdict.evaluate_disk(SA400, FAKE_ZERO_COUNTERS, SA400_SMART_ATTRS, 0, [], [])
    joined = "".join(v["reasons"])
    assert "未提供可靠的寿命数据" in joined, f"应说明未提供寿命数据: {joined}"
    assert "100%" not in joined, f"不应出现 100% 误导: {joined}"
    assert v["score"] == 100, f"硬件指标全零不应扣分，score={v['score']}"


def test_sa400_health_grade_unaffected():
    """健康分口径不变：这块盘确实是健康的（与 CDI「良好」、官方「Healthy」一致）。"""
    v = verdict.evaluate_disk(SA400, FAKE_ZERO_COUNTERS, SA400_SMART_ATTRS, 0, [], [])
    assert v["level"] == "healthy", f"应保持健康档，level={v['level']}"


def test_wear_100_false_alarm_not_regressed():
    """v1.2.0（#18）防线不回归：Wear=100 + 硬件干净仍判「未提供寿命数据」。"""
    v = verdict.evaluate_disk(SA400, dict(FAKE_ZERO_COUNTERS, Wear=100), SA400_SMART_ATTRS, 0, [], [])
    assert "未提供寿命数据" in "".join(v["reasons"]), "Wear=100 防线被破坏"
    assert v["score"] == 100, f"不应扣分，score={v['score']}"


def test_wear_95_real_measurement_still_judged():
    """反向保护：Wear=95 是真实测量，照常判读（剩余 5% 危险档）。"""
    v = verdict.evaluate_disk(SA400, dict(FAKE_ZERO_COUNTERS, Wear=95), SA400_SMART_ATTRS, 0, [], [])
    joined = "".join(v["reasons"])
    assert "未提供" not in joined, "Wear=95 不应判无数据"
    assert v["score"] < 80, f"剩余 5% 应重扣，score={v['score']}"


# ---------------- metrics 指标表层 ----------------

def test_metrics_shows_not_provided_for_fake_zero():
    """指标表那一行不能再显示「100%」，应显示「未提供」。"""
    result = {
        "disk": SA400,
        "counters": FAKE_ZERO_COUNTERS,
        "smart_attrs": SA400_SMART_ATTRS,
        "nvme_health": None,
    }
    row = _metric_row(result, "life_remaining")
    assert row is not None, "该行不应被隐藏"
    assert row["text"] == "未提供", f"文案不对: {row['text']}"
    assert row["level"] == metrics_mod.LEVEL_OK, f"不应是危险色，等级={row['level']}"
    assert "100%" not in str(row["text"]), f"不应再出现 100%: {row['text']}"


def test_metrics_nvme_uses_direct_read():
    """NVMe 指标表寿命行取直读值（54% 剩余），不用计数器的假 0。"""
    result = {
        "disk": NVME_DISK,
        "counters": NVME_COUNTERS,
        "smart_attrs": [],
        "nvme_health": NVME_HEALTH,
    }
    row = _metric_row(result, "life_remaining")
    assert row is not None and row["text"] == "54%", f"应显示 54%，实际={row}"


def test_metrics_no_signal_row_hidden():
    """完全没有任何寿命信号时，指标行仍然隐藏（不造假数据）。"""
    result = {
        "disk": SA400,
        "counters": {"Temperature": 38},
        "smart_attrs": SA400_SMART_ATTRS,
        "nvme_health": None,
    }
    assert _metric_row(result, "life_remaining") is None, "无信号时应隐藏该行"


# ---------------- 报告层 ----------------

def test_report_shows_not_provided():
    """HTML 报告同样口径，且不带误导性 100%。"""
    result = {
        "disk": SA400,
        "counters": FAKE_ZERO_COUNTERS,
        "smart_attrs": SA400_SMART_ATTRS,
        "nvme_health": None,
        "verdict": verdict.evaluate_disk(SA400, FAKE_ZERO_COUNTERS, SA400_SMART_ATTRS, 0, [], []),
        "all_volumes": [],
        "dirty_volumes": [],
    }
    html = report_mod.build_report_html([result])
    assert "未提供" in html, "报告应显示未提供寿命"
    assert "寿命剩余 100%" not in html and "剩余寿命（SSD）</td><td>100%" not in html, \
        "报告不应再出现误导性 100%"


def test_report_nvme_temp_has_caliber_note():
    """v1.2.2（#15）：报告的 NVMe 段落要带复合温度口径说明。"""
    result = {
        "disk": NVME_DISK,
        "counters": NVME_COUNTERS,
        "smart_attrs": [],
        "nvme_health": NVME_HEALTH,
        "verdict": verdict.evaluate_disk(NVME_DISK, NVME_COUNTERS, [], 0, [], []),
        "all_volumes": [],
        "dirty_volumes": [],
    }
    html = report_mod.build_report_html([result])
    assert "复合温度取盘内最高传感器" in html, "报告缺少复合温度口径说明"


# ---------------- verdict 判读层：NVMe 双路径协调 ----------------

def test_nvme_pct_deducts_once_no_double_count():
    """NVMe 直读使用率由 5.5 节判读，第 3 节让位——同一事实只扣一次分。"""
    v = verdict.evaluate_disk(NVME_DISK, None, [], 0, [], [], dict(NVME_HEALTH, percentage_used=92))
    assert v["score"] == 70, f"pct=92 应只扣 30 分，score={v['score']}"
    joined = "".join(v["reasons"])
    assert "已使用寿命" in joined, f"应说明已使用寿命: {joined}"
    assert joined.count("已使用寿命") + joined.count("寿命已消耗") == 1, "不得双重判读寿命"


def test_nvme_direct_read_wins_over_stale_counter():
    """v1.2.2（#20）：直读与计数器冲突时以直读为准（计数器可能滞后）。"""
    v = verdict.evaluate_disk(
        NVME_DISK, NVME_COUNTERS, [], 0, [], [], dict(NVME_HEALTH, percentage_used=92)
    )
    assert v["score"] == 70, f"应按直读 92% 扣 30 分，score={v['score']}"
    assert any("已使用寿命" in r for r in v["reasons"]), "应按直读值判读"


def test_nvme_pct_255_not_deducted():
    """NVMe 255=未上报：不扣分、说明未提供（旧代码会误扣成「已使用寿命 255%」）。"""
    counters = dict(NVME_COUNTERS, PowerOnHours=8600)
    v = verdict.evaluate_disk(NVME_DISK, counters, [], 0, [], [], dict(NVME_HEALTH, percentage_used=255))
    joined = "".join(v["reasons"])
    assert "未提供可靠的寿命数据" in joined, f"255 应判未提供: {joined}"
    assert "255%" not in joined and "已使用寿命" not in joined, "不得按 255% 扣分"
    assert v["score"] == 100, f"不应扣分，score={v['score']}"


# ---------------- 界面层（源码守卫） ----------------

def test_ui_subtitle_uses_shared_resolver():
    """界面摘要行必须与判读层同源（共用 resolve_wear_used），不能各算一套。"""
    assert "resolve_wear_used" in UI_SRC, "界面未接入共享寿命解析"
    assert "寿命未提供" in UI_SRC, "界面缺少「寿命未提供」文案"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
