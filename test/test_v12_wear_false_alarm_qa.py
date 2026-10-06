# -*- coding: utf-8 -*-
"""v1.2（#18）早期 SSD「0% 寿命」误报的回归测试。

坛友反馈场景：金士顿 SV300S37A240G（2013 年 SATA TLC 盘）被挖兔判为
「剩余寿命 0% 危险 / 立即备份并准备更换」，实际硬件指标全正常。

根因：该盘硬件不提供寿命/磨损数据，Windows 的 Get-StorageReliabilityCounter
会把 Wear 填成默认值 100；旧版无条件采信，等于用系统默认值误判好盘报废。

修复口径（三层统一，只抑制 wear==100 这一可疑默认值）：
- verdict  : 不扣 40 分、判「未提供寿命数据」，硬件正常则保持健康档；
- metrics  : 指标表该行显示「未提供（早期硬盘）」且不着红色危险色；
- report   : HTML 报告同样显示「未提供（早期硬盘）」。

反向保护：wear==100 但同时存在坏块 / NVMe 媒体错误时，仍按真实耗尽重扣。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import metrics as metrics_mod  # noqa: E402
from core import report as report_mod  # noqa: E402
from core import verdict  # noqa: E402

# 坛友实机：KINGSTON SV300S37A240G，ATA / SSD / 224GB
KINGSTON = {
    "device_id": "0",
    "model": "KINGSTON SV300S37A240G",
    "media_type": "SSD",
    "bus_type": "SATA",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 240 * 1024 ** 3,
    "serial": "50026F775B013F65",
}

# 该盘 SMART 明细里没有任何寿命属性，全是通电/温度/CRC 类
KINGSTON_SMART_ATTRS = [
    {"id": 0x09, "hex": "0x09", "name": "通电时间", "value": 57, "raw": 18861},
    {"id": 0x0C, "hex": "0x0C", "name": "通电次数", "value": 95, "raw": 8350},
    {"id": 0xC2, "hex": "0xC2", "name": "温度", "value": 181, "raw": 206158692385},
    {"id": 0xC7, "hex": "0xC7", "name": "接口传输错误（CRC）", "value": 200, "raw": 1},
]

# Windows 填的默认 Wear=100（无真实寿命数据）
DEFAULT_WEAR_COUNTERS = {
    "Temperature": 36,
    "Wear": 100,
    "PowerOnHours": 400,
    "ReadErrorsUncorrected": 0,
    "WriteErrorsUncorrected": 0,
}


def _metric_row(result: dict, key: str) -> dict | None:
    for item in metrics_mod.metric_items_for_result(result):
        if item.get("key") == key:
            return item
    return None


# ---------------- verdict 层 ----------------

def test_kingston_not_judged_worn_out():
    """核心断言：金士顿这块盘不该被判 0% 危险、更不该劝用户换盘。"""
    v = verdict.evaluate_disk(KINGSTON, DEFAULT_WEAR_COUNTERS, KINGSTON_SMART_ATTRS, 0, [], [])
    assert v["score"] == 100, f"不应扣分，score={v['score']}"
    assert v["level"] == "healthy", f"应保持健康档，level={v['level']}"
    joined = "".join(v["reasons"])
    assert "未提供寿命数据" in joined, f"应说明未提供寿命数据: {joined}"
    assert "立即备份并准备更换" not in joined, "不应劝用户更换硬盘"
    assert v["score"] >= 80, "综合评分应仍在健康区间"


def test_kingston_crc_1_no_cable_warning():
    """同批次回归：CRC=1 属微量，不扣分也不劝换 SATA 线。"""
    v = verdict.evaluate_disk(KINGSTON, DEFAULT_WEAR_COUNTERS, KINGSTON_SMART_ATTRS, 0, [], [])
    assert not any("更换 SATA 线" in r for r in v["reasons"]), f"CRC=1 不该劝换线: {v['reasons']}"


# ---------------- metrics 展示层 ----------------

def test_metrics_life_remaining_shows_not_provided():
    """指标表那一行不能再显示「0%」红色危险，应显示「未提供（早期硬盘）」。"""
    result = {
        "disk": KINGSTON,
        "counters": DEFAULT_WEAR_COUNTERS,
        "smart_attrs": KINGSTON_SMART_ATTRS,
        "nvme_health": None,
    }
    row = _metric_row(result, "life_remaining")
    assert row is not None, "该行不应被隐藏"
    assert row["text"] == "未提供（早期硬盘）", f"文案不对: {row['text']}"
    assert row["level"] == metrics_mod.LEVEL_OK, f"不应是危险色，等级={row['level']}"
    assert "0%" not in str(row["text"]), f"不应再出现 0%: {row['text']}"


# ---------------- 报告层 ----------------

def test_report_life_remaining_shows_not_provided():
    """HTML 报告同样口径。"""
    result = {
        "disk": KINGSTON,
        "counters": DEFAULT_WEAR_COUNTERS,
        "smart_attrs": KINGSTON_SMART_ATTRS,
        "nvme_health": None,
        "verdict": verdict.evaluate_disk(
            KINGSTON, DEFAULT_WEAR_COUNTERS, KINGSTON_SMART_ATTRS, 0, [], []
        ),
        "all_volumes": [],
        "dirty_volumes": [],
    }
    html = report_mod.build_report_html([result])
    assert "未提供（早期硬盘）" in html, "报告应显示未提供寿命"
    assert "剩余寿命 0%" not in html, f"报告不应再出现「剩余寿命 0%」"


# ---------------- 反向保护 ----------------

def test_wear_100_with_bad_sectors_still_warns():
    """有坏块时 Wear=100 属真实耗尽，必须照常重扣、不能被抑制。"""
    attrs = list(KINGSTON_SMART_ATTRS) + [
        {"id": 0xC5, "hex": "0xC5", "name": "待映射扇区数", "value": 100, "raw": 20}
    ]
    v = verdict.evaluate_disk(KINGSTON, DEFAULT_WEAR_COUNTERS, attrs, 0, [], [])
    assert "未提供寿命数据" not in "".join(v["reasons"]), "有坏块时不应抑制"
    assert v["score"] < 80, f"有硬件异常时评分应下降，score={v['score']}"


def test_wear_95_real_measurement_still_normal_display():
    """边界：Wear=95 是真实测量值，指标表照常显示百分比（不触发默认值抑制）。"""
    result = {
        "disk": KINGSTON,
        "counters": dict(DEFAULT_WEAR_COUNTERS, Wear=95),
        "smart_attrs": KINGSTON_SMART_ATTRS,
        "nvme_health": None,
    }
    row = _metric_row(result, "life_remaining")
    assert row is not None
    assert row["text"] == "5%", f"Wear=95 应显示 5%，实际={row['text']}"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
