# -*- coding: utf-8 -*-
"""v1.1 六档等级独立边界测试（QA 自编，不照抄工程师 selftest）。

覆盖：
- grade_of_score 全部分档边界（含 None / 非法值 / 负数 / 超界 / 布尔 / 浮点）；
- grade_of_verdict 封顶语义：Unhealthy（score 钳 49）必须显示危险红（grade<=1）、
  C5>0（score 钳 79）必须显示警告橙（grade<=2）、全优盘显示优秀深绿；
- v1.0 force_danger / force_warning 原规则回归（evaluate_disk）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import verdict  # noqa: E402
from core.verdict import (  # noqa: E402
    GRADE_CRITICAL,
    GRADE_DANGEROUS,
    GRADE_EXCELLENT,
    GRADE_FAIR,
    GRADE_GOOD,
    GRADE_UNKNOWN,
    GRADE_WARN,
    grade_of_score,
    grade_of_verdict,
)


# ----------------------------------------------------------------------
# grade_of_score 边界
# ----------------------------------------------------------------------
def test_grade_of_score_all_boundaries():
    cases = {
        0: GRADE_CRITICAL,
        24: GRADE_CRITICAL,
        25: GRADE_DANGEROUS,
        44: GRADE_DANGEROUS,
        45: GRADE_WARN,
        59: GRADE_WARN,
        60: GRADE_FAIR,
        74: GRADE_FAIR,
        75: GRADE_GOOD,
        89: GRADE_GOOD,
        90: GRADE_EXCELLENT,
        100: GRADE_EXCELLENT,
    }
    for score, expected in cases.items():
        actual = grade_of_score(score)
        assert actual == expected, f"grade_of_score({score}) = {actual}，期望 {expected}"


def test_grade_of_score_invalid_inputs():
    assert grade_of_score(None) == GRADE_UNKNOWN
    assert grade_of_score("abc") == GRADE_UNKNOWN
    assert grade_of_score("") == GRADE_UNKNOWN
    assert grade_of_score(object()) == GRADE_UNKNOWN
    # 布尔是 int 子类，但语义上不是分数 -> 未检测
    assert grade_of_score(True) == GRADE_UNKNOWN
    assert grade_of_score(False) == GRADE_UNKNOWN


def test_grade_of_score_out_of_range():
    # 负数与超界值：实现按数值大小映射（负数 -> 紧急，>100 -> 优秀），只要不抛异常且有确定档位
    assert grade_of_score(-1) == GRADE_CRITICAL
    assert grade_of_score(-999) == GRADE_CRITICAL
    assert grade_of_score(101) == GRADE_EXCELLENT
    assert grade_of_score(10000) == GRADE_EXCELLENT


def test_grade_of_score_numeric_strings_and_floats():
    # 数字字符串可转换则按分数分档（容错行为，与 int(score) 实现一致）
    assert grade_of_score("95") == GRADE_EXCELLENT
    assert grade_of_score("30") == GRADE_DANGEROUS
    # 浮点按 int 截断（不是四舍五入）：89.9 -> 89 良好
    assert grade_of_score(89.9) == GRADE_GOOD
    assert grade_of_score(90.0) == GRADE_EXCELLENT


# ----------------------------------------------------------------------
# grade_of_verdict 封顶语义（v1.1 设计关键）
# ----------------------------------------------------------------------
def _make_disk(health_status="Healthy"):
    return {
        "device_id": "0",
        "model": "Unit Disk",
        "media_type": "SSD",
        "bus_type": "NVMe",
        "health_status": health_status,
        "size": 512 * 1024 ** 3,
        "serial": "QA001",
    }


def test_grade_of_verdict_unhealthy_capped_to_danger_red():
    """Unhealthy 即使分数被钳到 49，托盘也必须是危险红（grade<=1），不能落警告橙。"""
    v = verdict.evaluate_disk(_make_disk("Unhealthy"), {"Temperature": 35}, [], 0, [], [])
    assert v["level"] == "danger", f"level={v['level']}"
    assert v["score"] <= 49, f"score={v['score']} 应被钳到 <=49"
    assert v["score"] >= 25, f"score={v['score']} 落在紧急档不符合钳 49 设计"
    grade = grade_of_verdict(v)
    assert grade == GRADE_DANGEROUS, f"grade={grade}，Unhealthy 托盘必须危险红(1)而不能是警告橙(2)"


def test_grade_of_verdict_c5_positive_capped_to_warning_orange():
    """C5>0 分数钳 79 后必须显示警告橙（grade<=2），不能按裸分数落良好绿。"""
    sata_disk = dict(_make_disk(), bus_type="SATA", media_type="HDD")
    smart_attrs = [{"id": 0xC5, "name": "待映射扇区数", "value": 100, "raw": 4}]
    v = verdict.evaluate_disk(sata_disk, {"Temperature": 35}, smart_attrs, 0, [], [])
    assert v["level"] == "warning", f"level={v['level']}"
    assert v["score"] == 79, f"score={v['score']} 应被钳到 79"
    grade = grade_of_verdict(v)
    assert grade == GRADE_WARN, f"grade={grade}，C5>0 托盘必须警告橙(2)而不能是良好绿(4)"


def test_grade_of_verdict_all_clear_is_excellent():
    """全优盘（无任何扣分项）应为优秀深绿 grade=5。"""
    v = verdict.evaluate_disk(
        _make_disk(),
        {"Temperature": 35, "Wear": 2, "ReadErrorsUncorrected": 0, "WriteErrorsUncorrected": 0},
        [],
        0,
        [],
        [],
    )
    assert v["level"] == "healthy" and v["score"] == 100, f"score={v['score']} level={v['level']}"
    assert grade_of_verdict(v) == GRADE_EXCELLENT


def test_grade_of_verdict_level_warning_caps_low_score_keep():
    """level=warning 但分数本身更低（如 55 -> 警告橙）：封顶只降不升。"""
    v = {"score": 55, "level": "warning"}
    assert grade_of_verdict(v) == GRADE_WARN  # min(2, cap2) 不变
    v2 = {"score": 30, "level": "warning"}
    assert grade_of_verdict(v2) == GRADE_DANGEROUS  # min(1, cap2) = 1，封顶不会把低分抬高


def test_grade_of_verdict_invalid_data():
    assert grade_of_verdict(None) == GRADE_UNKNOWN
    assert grade_of_verdict({}) == GRADE_UNKNOWN
    assert grade_of_verdict({"level": "healthy"}) == GRADE_UNKNOWN  # 无 score
    assert grade_of_verdict({"score": "abc"}) == GRADE_UNKNOWN
    # 未知 level 字符串：无 cap，按裸分数
    assert grade_of_verdict({"score": 96, "level": "mystery"}) == GRADE_EXCELLENT


# ----------------------------------------------------------------------
# v1.0 强制档原规则回归
# ----------------------------------------------------------------------
def test_force_danger_regression_unhealthy_always_danger():
    """v1.0 规则：HealthStatus=Unhealthy 强制危险档，即使其它指标全优。"""
    v = verdict.evaluate_disk(_make_disk("Unhealthy"), None, [], 0, [], [])
    assert v["level"] == "danger"
    assert v["score"] <= 49
    assert v["level_text"] == "危险"


def test_force_warning_regression_c5_blocks_healthy():
    """v1.0 规则：C5>0 强制至少警告档（score 钳 <=79）。"""
    sata_disk = dict(_make_disk(), bus_type="SATA", media_type="HDD")
    for c5_raw in (1, 5, 100):
        attrs = [{"id": 0xC5, "name": "待映射扇区数", "value": 100, "raw": c5_raw}]
        v = verdict.evaluate_disk(sata_disk, None, attrs, 0, [], [])
        assert v["level"] in ("warning", "danger"), f"C5={c5_raw} level={v['level']}"
        assert v["score"] <= 79, f"C5={c5_raw} score={v['score']} 必须 <=79"


def test_force_danger_priority_over_force_warning():
    """Unhealthy + C5>0 同时存在：危险优先（elif 分支）。"""
    sata_disk = dict(_make_disk("Unhealthy"), bus_type="SATA", media_type="HDD")
    attrs = [{"id": 0xC5, "name": "待映射扇区数", "value": 100, "raw": 10}]
    v = verdict.evaluate_disk(sata_disk, None, attrs, 0, [], [])
    assert v["level"] == "danger"
    assert v["score"] <= 49
    assert grade_of_verdict(v) == GRADE_DANGEROUS


def test_unhealthy_with_terrible_score_lands_critical_grade():
    """分数足够低（<25）时六档应为紧急红 0，封顶 min(0,1)=0 不受影响。"""
    disk = dict(_make_disk("Unhealthy"), media_type="SSD")
    v = verdict.evaluate_disk(
        disk,
        {"Temperature": 75, "Wear": 98, "ReadErrorsUncorrected": 500, "WriteErrorsUncorrected": 500},
        [],
        30,
        [{"time": "t", "provider": "disk", "level_text": "错误", "message": "x"}],
        [{"drive": "C:", "dirty": True, "disk_number": 0}],
    )
    assert v["level"] == "danger"
    assert v["score"] < 25, f"score={v['score']} 应 <25"
    assert grade_of_verdict(v) == GRADE_CRITICAL


def test_grade_tables_consistency():
    """六档颜色 / 标签表必须覆盖 -1..5 且相互键一致。"""
    assert set(verdict.GRADE_COLORS.keys()) == {-1, 0, 1, 2, 3, 4, 5}
    assert set(verdict.GRADE_LABELS.keys()) == {-1, 0, 1, 2, 3, 4, 5}
    assert set(verdict.GRADE_COLORS.keys()) == set(verdict.GRADE_LABELS.keys())
    # 颜色均为合法 #RRGGBB
    for color in verdict.GRADE_COLORS.values():
        assert color.startswith("#") and len(color) == 7
        int(color[1:], 16)
    # 标签互不相同
    assert len(set(verdict.GRADE_LABELS.values())) == 7


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
