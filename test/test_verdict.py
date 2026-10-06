# -*- coding: utf-8 -*-
"""verdict.py 评分引擎独立单元测试（QA 自编，不复用 main.py --selftest 断言）。

覆盖边界：
- 全优盘 = 100 分 / 健康；
- C6 / C5 / 05 / C7 各扣分档位与分数边界；
- SSD Wear 剩余寿命各档（<10% / <20% / <50%）；
- 温度 60 / 70 档；
- 事件数 1 / 3 / 8 / 20 条各档；
- 卷损坏位置位；
- HealthStatus = Warning / Unhealthy；
- 零数据 / None 输入不崩溃且给出降级理由；
- 极端叠加扣分下限 0 分、危险结论；
- summarize 汇总。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import verdict  # noqa: E402

BASE_DISK = {
    "device_id": "0",
    "model": "UnitTest SATA HDD",
    "media_type": "HDD",
    "bus_type": "SATA",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 1000 * 1024 ** 3,
    "serial": "UTSERIAL001",
}

SSD_DISK = dict(BASE_DISK, media_type="SSD", bus_type="NVMe")


def _mk_attr(attr_id: int, raw: int) -> dict:
    return {"id": attr_id, "hex": f"0x{attr_id:02X}", "name": f"attr{attr_id}", "value": 100, "raw": raw}


GOOD_COUNTERS = {"Temperature": 35, "Wear": 0, "ReadErrorsUncorrected": 0, "WriteErrorsUncorrected": 0}


def test_perfect_disk_score_100_healthy():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 0, [], [])
    assert result["score"] == 100, f"score={result['score']}"
    assert result["level"] == "healthy"
    assert result["level_text"] == "健康"
    assert result["reasons"], "健康盘也必须有理由文本"


def test_c6_one_pending_sector_deduct_45():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC6, 1)], 0, [], [])
    assert result["score"] == 55, f"C6=1 应扣 45 分，score={result['score']}"
    assert result["level"] == "warning"
    assert any("无法修正" in r for r in result["reasons"])


def test_c6_large_raw_reason_contains_count():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC6, 88)], 0, [], [])
    assert result["score"] == 55, f"C6 扣分为固定 45，score={result['score']}"
    assert any("88" in r for r in result["reasons"]), "理由应包含坏扇区数量"


def test_c5_small_pending_forced_warning():
    """C5=1 扣 20 分 -> 80 分，但任何非零 C5 强制至少「警告」档（score 钳到 79）。"""
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC5, 1)], 0, [], [])
    assert result["score"] == 79, f"C5=1 扣 20 分后钳到 79，score={result['score']}"
    assert result["level"] == "warning"


def test_c5_medium_pending_warning():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC5, 8)], 0, [], [])
    assert result["score"] == 79, f"C5=8 扣 min(35, 20+1)=21 -> 79，score={result['score']}"
    assert result["level"] == "warning"


def test_c5_huge_pending_deduct_capped_35():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC5, 100000)], 0, [], [])
    assert result["score"] == 65, f"C5 封顶扣 35 分，score={result['score']}"


def test_reallocated_05_small():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0x05, 4)], 0, [], [])
    assert result["score"] == 92, f"05=4 扣 8+0=8 分，score={result['score']}"
    assert result["level"] == "healthy"


def test_reallocated_05_capped_25():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0x05, 5000)], 0, [], [])
    assert result["score"] == 75, f"05 封顶扣 25 分，score={result['score']}"
    assert result["level"] == "warning"


def test_crc_c7_small():
    """v1.2（#16）：C7=50 属微量累计（<100 告警阈值）——不扣分、不劝换线，仅安抚告知。"""
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC7, 50)], 0, [], [])
    assert result["score"] == 100, f"C7=50 微量不扣分，score={result['score']}"
    assert result["level"] == "healthy"
    assert any("CRC" in r and "无需处理" in r for r in result["reasons"]), f"应给安抚说明: {result['reasons']}"
    assert not any("更换 SATA 线" in r for r in result["reasons"]), "微量 CRC 不应弹换线建议"


def test_crc_c7_2_no_score_loss():
    """坛友场景：TOSHIBA 报 2 次 CRC，指标判正常却曾被扣分并劝换线——v1.2 起不扣分。"""
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC7, 2)], 0, [], [])
    assert result["score"] == 100, f"C7=2 不扣分，score={result['score']}"
    assert not any("更换 SATA 线" in r for r in result["reasons"]), f"C7=2 不该劝换线: {result['reasons']}"
    assert any("无需处理" in r for r in result["reasons"]), "应说明属正常范围偶发"


def test_crc_c7_over_threshold_still_warns():
    """v1.2（#16）：C7 >= 100 告警阈值才扣分并提示换线。"""
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC7, 500)], 0, [], [])
    assert result["score"] == 92, f"C7=500 扣 min(10,3+5)=8 分，score={result['score']}"
    assert any("更换 SATA 线" in r for r in result["reasons"]), "超阈值应提示换线"


def test_crc_c7_capped_10():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC7, 99999)], 0, [], [])
    assert result["score"] == 90, f"C7 封顶扣 10 分，score={result['score']}"


def test_ssd_wear_below_10_percent():
    result = verdict.evaluate_disk(SSD_DISK, dict(GOOD_COUNTERS, Wear=95), [], 0, [], [])
    assert result["score"] == 60, f"Wear=95 扣 40 分，score={result['score']}"
    assert result["level"] == "warning"
    assert any("寿命" in r for r in result["reasons"])


# ---- v1.2（#18）早期 SSD 无寿命数据的 0% 误报（金士顿 SV300S37A240G 场景） ----

def test_ssd_wear_100_hardware_clean_not_judged_worn_out():
    """坛友场景：早期 SATA SSD 无寿命数据，Windows 把 Wear 填成默认 100。

    此时重映射/待映射/无法修正扇区全为 0，不应判「寿命耗尽」并扣 40 分，
    更不应把用户吓到去扔一块好盘。
    """
    result = verdict.evaluate_disk(SSD_DISK, dict(GOOD_COUNTERS, Wear=100), [], 0, [], [])
    assert result["score"] == 100, f"无寿命数据不应扣分，score={result['score']}"
    assert result["level"] == "healthy"
    joined = "".join(result["reasons"])
    assert "未提供寿命数据" in joined, f"应说明未提供寿命数据: {joined}"
    assert "立即备份并准备更换" not in joined, "不应劝用户更换硬盘"


def test_ssd_wear_100_with_bad_sectors_still_warns():
    """反向保护：若同时存在坏块等硬件异常，Wear=100 仍应按真实耗尽重扣。"""
    result = verdict.evaluate_disk(
        SSD_DISK, dict(GOOD_COUNTERS, Wear=100), [_mk_attr(0xC5, 20)], 0, [], []
    )
    # C5=20 扣 min(35, 20+2)=22，Wear=100 重扣 40 -> 38，force_warning 钳制
    assert any("寿命" in r for r in result["reasons"]), f"有硬件信号时仍应提示寿命: {result['reasons']}"
    assert result["level"] in ("warning", "danger"), f"应至少警告档，level={result['level']}"


def test_ssd_wear_95_is_real_measurement_not_suppressed():
    """边界：Wear=95 是真实测量值（≠系统默认 100），不该被「无数据」规则误伤。"""
    result = verdict.evaluate_disk(SSD_DISK, dict(GOOD_COUNTERS, Wear=95), [], 0, [], [])
    assert result["score"] == 60, f"Wear=95 属真实测量应照常扣分，score={result['score']}"
    assert "未提供寿命数据" not in "".join(result["reasons"]), "Wear=95 不应被当作无数据"


def test_ssd_wear_100_nvme_media_errors_warns():
    """NVMe 盘：Wear=100 但有媒体错误时不应被抑制。"""
    result = verdict.evaluate_disk(
        SSD_DISK, dict(GOOD_COUNTERS, Wear=100), [], 0, [], [],
        {"media_errors": 5, "percentage_used": 100},
    )
    assert "未提供寿命数据" not in "".join(result["reasons"]), "有媒体错误时不应抑制"


def test_ssd_wear_10_to_20_percent():
    result = verdict.evaluate_disk(SSD_DISK, dict(GOOD_COUNTERS, Wear=85), [], 0, [], [])
    assert result["score"] == 75, f"Wear=85 剩余 15% 扣 25 分，score={result['score']}"


def test_ssd_wear_20_to_50_percent():
    result = verdict.evaluate_disk(SSD_DISK, dict(GOOD_COUNTERS, Wear=60), [], 0, [], [])
    assert result["score"] == 90, f"Wear=60 剩余 40% 扣 10 分，score={result['score']}"
    assert result["level"] == "healthy"


def test_ssd_wear_zero_no_deduction():
    result = verdict.evaluate_disk(SSD_DISK, dict(GOOD_COUNTERS, Wear=0), [], 0, [], [])
    assert result["score"] == 100


def test_ssd_wear_none_no_deduction_no_crash():
    """HDD 盘 Wear 通常为 None，不应扣分也不应崩溃。"""
    result = verdict.evaluate_disk(BASE_DISK, {"Temperature": 35, "Wear": None}, [], 0, [], [])
    assert result["score"] == 100


def test_hdd_media_wear_ignored():
    """HDD 即使误带 Wear=99 也不应触发 SSD 寿命扣分。"""
    result = verdict.evaluate_disk(BASE_DISK, dict(GOOD_COUNTERS, Wear=99), [], 0, [], [])
    assert result["score"] == 100, f"HDD 不做 SSD 寿命扣分，score={result['score']}"


def test_temperature_70_deduct_15():
    result = verdict.evaluate_disk(BASE_DISK, dict(GOOD_COUNTERS, Temperature=70), [], 0, [], [])
    assert result["score"] == 85, f"70°C 扣 15 分，score={result['score']}"
    assert result["level"] == "healthy"
    assert any("温度" in r for r in result["reasons"])


def test_temperature_above_70_deduct_15():
    result = verdict.evaluate_disk(BASE_DISK, dict(GOOD_COUNTERS, Temperature=75), [], 0, [], [])
    assert result["score"] == 85


def test_temperature_60_deduct_8():
    result = verdict.evaluate_disk(BASE_DISK, dict(GOOD_COUNTERS, Temperature=60), [], 0, [], [])
    assert result["score"] == 92, f"60°C 扣 8 分，score={result['score']}"


def test_temperature_zero_or_negative_ignored():
    result = verdict.evaluate_disk(BASE_DISK, dict(GOOD_COUNTERS, Temperature=0), [], 0, [], [])
    assert result["score"] == 100


def test_uncorrected_read_errors_deduct():
    result = verdict.evaluate_disk(BASE_DISK, dict(GOOD_COUNTERS, ReadErrorsUncorrected=120), [], 0, [], [])
    assert result["score"] == 90, f"120 次未修正读错误扣 min(15, 8+2)=10 分，score={result['score']}"
    assert any("读取" in r for r in result["reasons"])


def test_events_1_deduct_8():
    recent = [{"time": "t", "provider": "disk", "level": 2, "level_text": "错误", "message": "坏块"}]
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 1, recent, [])
    assert result["score"] == 92, f"1 条事件扣 8 分，score={result['score']}"
    assert any("1 条" in r for r in result["reasons"])


def test_events_3_deduct_15():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 3, [], [])
    assert result["score"] == 85, f"3 条事件扣 15 分，score={result['score']}"
    assert result["level"] == "healthy"


def test_events_8_deduct_25():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 8, [], [])
    assert result["score"] == 75, f"8 条事件扣 25 分，score={result['score']}"
    assert result["level"] == "warning"


def test_events_20_deduct_40():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 20, [], [])
    assert result["score"] == 60, f"20 条事件扣 40 分，score={result['score']}"


def test_events_100_deduct_40_capped():
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 100, [], [])
    assert result["score"] == 60, f"事件扣分封顶 40，score={result['score']}"


def test_dirty_volume_light_penalty_no_hardware_signal():
    """v1.2（#13）：仅有脏位、其它指标正常 -> 轻扣（12 分），不再重扣 40。"""
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [], 0, [], [{"drive": "C:", "dirty": True, "disk_number": 0}])
    assert result["score"] == 88, f"仅脏位应轻扣 12 分，score={result['score']}"
    assert result["level"] == "healthy"
    assert any("C:" in r and "脏位" in r for r in result["reasons"])
    joined = "".join(result["reasons"])
    assert "可能存在损坏" not in joined, "不应再用「可能存在损坏」强暗示硬件故障"
    assert "chkdsk" in joined, "应给出可执行的修复指引 chkdsk /f"


def test_dirty_exfat_emphasises_not_hardware_failure():
    """坛友场景：exFAT + PS5 的新盘报脏位但寿命 100%——应安抚「不代表硬件损坏」。"""
    result = verdict.evaluate_disk(
        SSD_DISK, dict(GOOD_COUNTERS, Wear=0), [], 0, [],
        [{"drive": "E:", "dirty": True, "disk_number": 0, "fstype": "exFAT"}],
    )
    joined = "".join(result["reasons"])
    assert "不代表硬盘硬件损坏" in joined or "与硬盘硬件健康无关" in joined, f"exFAT 脏位需安抚: {joined}"
    assert "PS5" in joined or "未安全弹出" in joined or "其他设备" in joined, f"应说明常见成因: {joined}"


def test_dirty_with_hardware_signal_keeps_heavy_penalty():
    """v1.2（#13）：脏位与硬件异常信号并存 -> 维持重扣 40 分（叠加问题更严重）。"""
    result = verdict.evaluate_disk(
        BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC5, 100)], 0, [],
        [{"drive": "C:", "dirty": True, "disk_number": 0}],
    )
    # C5=100 扣 min(35, 20+100//8)=32，脏位重扣 40 -> 100-32-40=28
    assert result["score"] == 28, f"硬件信号并存时脏位应重扣，score={result['score']}"
    assert result["level"] == "danger"


def test_dirty_volume_heavy_penalty_with_c6():
    """脏位 + C6 无法修正扇区并存：维持重扣，且文案应偏「尽快处理」。"""
    result = verdict.evaluate_disk(
        BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC6, 10)], 0, [],
        [{"drive": "C:", "dirty": True, "disk_number": 0}],
    )
    # C6 扣 45 + 脏位重扣 40 -> 15；未触发 force 钳制
    assert result["score"] == 15, f"C6 并存时脏位应重扣，score={result['score']}"
    joined = "".join(result["reasons"])
    assert "硬件异常" in joined, f"并存时应说明硬件也有异常: {joined}"


def test_health_status_unhealthy_forced_danger():
    """Unhealthy 扣 50 分 -> 50 分，再被硬性结论钳到危险区间（score=49）强制「危险」档。"""
    result = verdict.evaluate_disk(dict(BASE_DISK, health_status="Unhealthy"), GOOD_COUNTERS, [], 0, [], [])
    assert result["score"] == 49, f"Unhealthy 强制危险档，score={result['score']}"
    assert result["level"] == "danger"
    assert any("不健康" in r or "Unhealthy" in r for r in result["reasons"]), "理由应强化为「系统已报告此盘不健康」"


def test_health_status_warning_deduct_15():
    result = verdict.evaluate_disk(dict(BASE_DISK, health_status="Warning"), GOOD_COUNTERS, [], 0, [], [])
    assert result["score"] == 85, f"Warning 扣 15 分，score={result['score']}"
    assert result["level"] == "healthy"


def test_all_none_inputs_no_crash_with_degraded_reason():
    """零数据 / None 输入：不崩溃、给出降级理由、仍有评分结论。"""
    result = verdict.evaluate_disk(BASE_DISK, None, None, 0, None, None)
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert result["level"] in ("healthy", "warning", "danger")
    assert any("管理员" in r or "无法读取" in r for r in result["reasons"]), f"缺降级理由: {result['reasons']}"


def test_counters_but_no_smart_no_degraded_reason():
    """有 counters 无 SMART（NVMe 正常情形）不应出现降级提示。"""
    result = verdict.evaluate_disk(SSD_DISK, GOOD_COUNTERS, [], 0, [], [])
    assert not any("无法读取" in r for r in result["reasons"])


def test_malformed_smart_attrs_skipped():
    """smart_attrs 里混入缺 id / 非法 id 的项应被跳过而非崩溃；十进制字符串 id 应被 int() 转换生效。"""
    attrs = [{"bad_key": 1}, {"id": "198", "raw": 1}, {"id": None}, "junk"]  # 198 == 0xC6
    result = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, attrs, 0, [], [])
    assert result["score"] == 55, f"字符串 id '198' 应被 int() 转换生效扣 45 分，score={result['score']}"


def test_extreme_worst_case_clamped_to_zero_danger():
    result = verdict.evaluate_disk(
        dict(BASE_DISK, health_status="Unhealthy"),
        {"Temperature": 80, "Wear": 99, "ReadErrorsUncorrected": 500, "WriteErrorsUncorrected": 500},
        [_mk_attr(0xC6, 10), _mk_attr(0xC5, 100), _mk_attr(0x05, 4000), _mk_attr(0xC7, 5000)],
        50,
        [{"time": "t", "provider": "disk", "level": 2, "level_text": "错误", "message": "x"}],
        [{"drive": "C:", "dirty": True, "disk_number": 0}],
    )
    assert result["score"] == 0, f"极端劣盘应钳制到 0 分，score={result['score']}"
    assert result["level"] == "danger"


def test_reasons_are_plain_chinese():
    result = verdict.evaluate_disk(
        SSD_DISK, dict(GOOD_COUNTERS, Wear=96), [_mk_attr(0xC6, 3)], 25, [], [{"drive": "D:", "dirty": True, "disk_number": 0}]
    )
    joined = "".join(result["reasons"])
    assert "备份" in joined, "面向普通用户的理由应包含「备份」建议"


def test_summarize_counts():
    ok = {"verdict": {"level": "healthy"}}
    warn = {"verdict": {"level": "warning"}}
    bad = {"verdict": {"level": "danger"}}
    assert verdict.summarize([ok, warn, bad, bad]) == {"total": 4, "healthy": 1, "warning": 1, "danger": 2}


def test_summarize_empty_and_missing_verdict():
    assert verdict.summarize([]) == {"total": 0, "healthy": 0, "warning": 0, "danger": 0}
    assert verdict.summarize([{}])["total"] == 1


def test_grade_of_score_boundaries():
    """六档等级映射边界（v1.1）。"""
    cases = {
        0: 0, 24: 0, 25: 1, 44: 1, 45: 2, 59: 2,
        60: 3, 74: 3, 75: 4, 89: 4, 90: 5, 100: 5,
    }
    for score, expected in cases.items():
        assert verdict.grade_of_score(score) == expected, f"score={score} -> {verdict.grade_of_score(score)}"


def test_grade_of_score_invalid_inputs():
    assert verdict.grade_of_score(None) == verdict.GRADE_UNKNOWN
    assert verdict.grade_of_score("abc") == verdict.GRADE_UNKNOWN
    assert verdict.grade_of_score(True) == verdict.GRADE_UNKNOWN  # bool 视为无效
    assert verdict.grade_of_score(-5) == 0, "负分应钳到最差档（紧急）"


def test_grade_of_verdict_and_tables():
    assert verdict.grade_of_verdict({"score": 96}) == 5
    assert verdict.grade_of_verdict({"score": 79}) == 4
    assert verdict.grade_of_verdict({"score": 49}) == 2
    assert verdict.grade_of_verdict({}) == verdict.GRADE_UNKNOWN
    assert verdict.grade_of_verdict(None) == verdict.GRADE_UNKNOWN
    assert set(verdict.GRADE_COLORS) == {-1, 0, 1, 2, 3, 4, 5}
    assert set(verdict.GRADE_LABELS) == {-1, 0, 1, 2, 3, 4, 5}
    assert verdict.GRADE_COLORS[5] == "#1FAF52"  # v1.2.1 翠绿（用户反馈深绿压抑）
    assert verdict.GRADE_COLORS[0] == "#8A1E1E"
    assert verdict.GRADE_COLORS[-1] == "#9AA0A6"


def test_grade_matches_force_semantics():
    """六档与 force_danger / force_warning 语义对齐：Unhealthy 落危险档(<=1)，C5 至少警告档(<=2)。"""
    danger = verdict.evaluate_disk(dict(BASE_DISK, health_status="Unhealthy"), GOOD_COUNTERS, [], 0, [], [])
    assert verdict.grade_of_verdict(danger) <= 1, f"Unhealthy 应落在危险/紧急档，grade={danger['score']}"
    c5 = verdict.evaluate_disk(BASE_DISK, GOOD_COUNTERS, [_mk_attr(0xC5, 1)], 0, [], [])
    assert verdict.grade_of_verdict(c5) <= 2, f"C5>0 至少警告档，grade={c5['score']}"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
