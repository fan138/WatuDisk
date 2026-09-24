# -*- coding: utf-8 -*-
"""综合评分与判读引擎（纯逻辑、无 IO，便于单元测试）。

输入各检测项结果，输出每块盘 0-100 分与结论：
- 健康   >= 80 分
- 警告   50 - 79 分
- 危险   <  50 分
以及大白话理由列表（面向不懂代码的个人用户）。
"""
from __future__ import annotations

LEVEL_HEALTHY = "healthy"
LEVEL_WARNING = "warning"
LEVEL_DANGER = "danger"

LEVEL_TEXT = {LEVEL_HEALTHY: "健康", LEVEL_WARNING: "警告", LEVEL_DANGER: "危险"}

# ---- 六档健康等级（v1.1，用于托盘图标配色 / 卡片徽章细化） ----
# 约定：数值越大越健康；GRADE_UNKNOWN 表示未检测。
GRADE_CRITICAL = 0    # 0-24   紧急 · 深红
GRADE_DANGEROUS = 1   # 25-44  危险 · 红
GRADE_WARN = 2        # 45-59  警告 · 橙
GRADE_FAIR = 3        # 60-74  注意 · 琥珀
GRADE_GOOD = 4        # 75-89  良好 · 浅绿
GRADE_EXCELLENT = 5   # 90-100 优秀 · 翠绿
GRADE_UNKNOWN = -1    # 未检测 · 灰

GRADE_COLORS: dict[int, str] = {
    GRADE_EXCELLENT: "#1FAF52",
    GRADE_GOOD: "#67C23A",
    GRADE_FAIR: "#D99A0B",
    GRADE_WARN: "#DD6B1D",
    GRADE_DANGEROUS: "#C93A3A",
    GRADE_CRITICAL: "#8A1E1E",
    GRADE_UNKNOWN: "#9AA0A6",
}

GRADE_LABELS: dict[int, str] = {
    GRADE_EXCELLENT: "优秀",
    GRADE_GOOD: "良好",
    GRADE_FAIR: "注意",
    GRADE_WARN: "警告",
    GRADE_DANGEROUS: "危险",
    GRADE_CRITICAL: "紧急",
    GRADE_UNKNOWN: "未检测",
}


def grade_of_score(score: object) -> int:
    """把 0-100 分映射为六档健康等级（0 最差，5 最好；未知返回 GRADE_UNKNOWN）。

    分档边界（左闭右闭）：
        90-100 -> 5 优秀 / 75-89 -> 4 良好 / 60-74 -> 3 注意
        45-59  -> 2 警告 / 25-44 -> 1 危险 /  0-24 -> 0 紧急
    """
    if score is None or isinstance(score, bool):
        return GRADE_UNKNOWN
    try:
        value = int(score)
    except (TypeError, ValueError):
        return GRADE_UNKNOWN
    if value >= 90:
        return GRADE_EXCELLENT
    if value >= 75:
        return GRADE_GOOD
    if value >= 60:
        return GRADE_FAIR
    if value >= 45:
        return GRADE_WARN
    if value >= 25:
        return GRADE_DANGEROUS
    return GRADE_CRITICAL


def grade_of_verdict(verdict_data: dict | None) -> int:
    """从 evaluate_disk 的返回值取六档等级；无有效数据返回 GRADE_UNKNOWN。

    若结论带有三档 level 字段，则用其封顶六档，保证与 force_danger /
    force_warning 语义一致：例如 Unhealthy 钳到 49 分后托盘仍显示
    「危险红」而非「警告橙」，C5 钳到 79 分后仍显示「警告橙」而非「良好绿」。
    """
    if not verdict_data:
        return GRADE_UNKNOWN
    grade = grade_of_score(verdict_data.get("score"))
    if grade == GRADE_UNKNOWN:
        return GRADE_UNKNOWN
    cap = _LEVEL_GRADE_CAP.get(str(verdict_data.get("level") or ""))
    return min(grade, cap) if cap is not None else grade


# 三档结论 -> 允许的最高六档等级（封顶，防止强制档被分数配色冲淡）
_LEVEL_GRADE_CAP: dict[str, int] = {
    LEVEL_DANGER: GRADE_DANGEROUS,
    LEVEL_WARNING: GRADE_WARN,
    LEVEL_HEALTHY: GRADE_EXCELLENT,
}

# 评分重点关注 SMART 属性
_SMART_C6 = 0xC6  # 无法修正扇区
_SMART_C5 = 0xC5  # 待映射扇区
_SMART_05 = 0x05  # 重映射扇区
_SMART_C7 = 0xC7  # 接口传输错误（CRC）


def _raw_of(smart_map: dict[int, dict], attr_id: int) -> int:
    """取指定属性的原始值，缺失返回 0。"""
    attr = smart_map.get(attr_id)
    if not attr:
        return 0
    try:
        return int(attr.get("raw") or 0)
    except (TypeError, ValueError):
        return 0


def _to_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def evaluate_disk(
    disk: dict,
    counters: dict | None = None,
    smart_attrs: list[dict] | None = None,
    error_events: int = 0,
    recent_events: list[dict] | None = None,
    dirty_volumes: list[dict] | None = None,
    nvme_health: dict | None = None,
) -> dict:
    """对单块磁盘做综合评分与判读。

    Args:
        disk: 磁盘基础信息（get_physical_disks 的单项）。
        counters: 可靠性计数器（温度 / Wear / 错误计数），无数据传 None。
        smart_attrs: SATA SMART 属性列表（NVMe 盘传空列表）。
        error_events: 过去 30 天与该盘相关的错误 / 警告事件数。
        recent_events: 最近几条相关事件（用于理由中引用示例）。
        dirty_volumes: 该盘上损坏位已置位的分区列表。
        nvme_health: NVMe 健康日志直读结果（core.nvme_health），无数据传 None。

    Returns:
        {"score": int, "level": str, "level_text": str, "reasons": list[str]}
    """
    reasons: list[str] = []
    score = 100.0
    # 强制档位标志：某些信号本身就是硬性结论，不允许仅靠扣分落在错误档位。
    force_danger = False   # 系统已报告 Unhealthy -> 无论得分多少强制「危险」
    force_warning = False  # C5 > 0 -> 无论得分多少至少「警告」

    smart = {}
    for attr in smart_attrs or []:
        try:
            smart[int(attr["id"])] = attr
        except (KeyError, TypeError, ValueError):
            continue

    had_counters = counters is not None
    had_smart = bool(smart_attrs)
    counters = counters or {}
    recent_events = recent_events or []
    dirty_volumes = dirty_volumes or []

    def deduct(points: float, reason: str) -> None:
        """扣分并记录大白话理由。"""
        nonlocal score
        score -= points
        reasons.append(reason)

    # ---- 1) 系统级健康状态（Get-PhysicalDisk） ----
    health = str(disk.get("health_status") or "").lower()
    if health == "unhealthy":
        force_danger = True
        deduct(50, "系统已报告此盘不健康（Unhealthy），硬件可能已出现故障，请立即备份重要数据并准备更换硬盘。")
    elif health == "warning":
        deduct(15, "系统对这块盘发出了「警告」状态提示，建议尽快备份数据并持续观察。")

    # ---- 2) SMART 关键属性（SATA 盘） ----
    c6 = _raw_of(smart, _SMART_C6)
    if c6 > 0:
        deduct(45, f"检测到 {c6} 个无法修正的坏扇区，数据已经有实际损坏风险，请立即备份数据并考虑更换硬盘。")

    c5 = _raw_of(smart, _SMART_C5)
    if c5 > 0:
        force_warning = True
        deduct(min(35, 20 + c5 // 8), f"有 {c5} 个扇区出现异常、正等待系统替换（待映射扇区），这是坏道出现的前兆，建议先备份数据再持续观察。")

    c05 = _raw_of(smart, _SMART_05)
    if c05 > 0:
        deduct(min(25, 8 + c05 // 16), f"这块盘已出现 {c05} 个坏块并被备用块替换，说明盘开始老化，建议尽快备份数据。")

    c7 = _raw_of(smart, _SMART_C7)
    if c7 > 0:
        deduct(min(10, 3 + c7 // 100), f"检测到 {c7} 次接口传输错误（CRC），多数是数据线或接口接触不良，台式机可尝试更换 SATA 线后重新检测。")

    # ---- 3) SSD 磨损（Wear 为已消耗寿命百分比，剩余 = 100 - Wear） ----
    media = str(disk.get("media_type") or "").upper()
    bus = str(disk.get("bus_type") or "").upper()
    is_ssd = media == "SSD" or bus == "NVME"
    wear_used = _to_int(counters.get("Wear")) if counters else None
    if is_ssd and wear_used is not None and wear_used >= 0:
        remaining = max(0, 100 - wear_used)
        if remaining < 10:
            deduct(40, f"这块 SSD 的寿命已消耗约 {wear_used}%（剩余不足 10%），已接近设计寿命终点，请立即备份并准备更换。")
        elif remaining < 20:
            deduct(25, f"这块 SSD 的剩余寿命约 {remaining}%，磨损明显加快，建议减少大文件反复写入并尽早备份。")
        elif remaining < 50:
            deduct(10, f"这块 SSD 的剩余寿命约 {remaining}%，属于正常消耗，建议保持定期备份的习惯。")

    # ---- 4) 温度 ----
    temp = _to_int(counters.get("Temperature")) if counters else None
    if temp is not None and temp > 0:
        if temp >= 70:
            deduct(15, f"当前温度 {temp}°C 过高，长期高温会显著加速硬盘老化甚至损坏，建议清理灰尘、改善机箱散热。")
        elif temp >= 60:
            deduct(8, f"当前温度 {temp}°C 偏高，建议检查散热风扇与通风情况。")

    # ---- 5) 无法修正的读 / 写错误计数 ----
    if counters:
        for key, label in (("ReadErrorsUncorrected", "读取"), ("WriteErrorsUncorrected", "写入")):
            value = _to_int(counters.get(key))
            if value is not None and value > 0:
                deduct(min(15, 8 + value // 50), f"累计出现 {value:,} 次无法修正的{label}错误，盘体可能存在物理损伤，建议尽快备份重要数据。")

    # ---- 5.5) NVMe 健康日志（v1.2 直读通道；无数据时整体跳过，不影响既有规则） ----
    nvme = nvme_health or {}
    if nvme:
        # 危险警告信号：NVMe 固件自报关键告警（备用空间不足 / 过温 / 介质退化等）
        critical_warning = _to_int(nvme.get("critical_warning")) or 0
        if critical_warning > 0:
            force_danger = True
            deduct(50, "硬盘自报危险警告信号，硬件可能已出现严重问题，建议立即备份数据。")

        # 可用备用空间：低于固件阈值或低于 10% 属于硬性风险
        spare = _to_int(nvme.get("available_spare_pct"))
        spare_thr = _to_int(nvme.get("spare_threshold"))
        spare_low = spare is not None and (
            (spare_thr is not None and spare < spare_thr) or spare < 10
        )
        if spare_low:
            force_warning = True
            threshold_text = spare_thr if spare_thr is not None else 10
            deduct(
                40,
                f"硬盘的可用备用空间只剩 {spare}%（告警阈值 {threshold_text}%），"
                "坏块快没有可替换的空间了，请立即备份数据。",
            )

        # 媒体错误（坏块）：每个扣 8 分，封顶 24 分
        media_errors = _to_int(nvme.get("media_errors"))
        if media_errors is not None and media_errors > 0:
            deduct(
                min(24, 8 * media_errors),
                f"硬盘已记录 {media_errors:,} 个媒体错误（坏块），"
                "说明存储介质开始出现损伤，建议尽快备份数据并持续观察。",
            )

        # 不安全断电：经常异常断电会损伤硬盘与数据，轻扣提示
        unsafe_shutdowns = _to_int(nvme.get("unsafe_shutdowns"))
        if unsafe_shutdowns is not None and unsafe_shutdowns > 100:
            deduct(
                5,
                f"累计发生 {unsafe_shutdowns:,} 次不正常断电（未正常关机），"
                "频繁异常断电会缩短硬盘寿命，建议尽量正常关机。",
            )

        # 使用率（NVMe Percentage Used）：Wear 通道有数据时不重复扣（避免双重计磨损）
        percentage_used = _to_int(nvme.get("percentage_used"))
        if is_ssd and wear_used is None and percentage_used is not None and percentage_used > 0:
            if percentage_used >= 90:
                deduct(
                    30,
                    f"这块 SSD 的已使用寿命约 {percentage_used}%，接近设计寿命终点，"
                    "请立即备份数据并准备更换。",
                )
            elif percentage_used >= 80:
                deduct(
                    15,
                    f"这块 SSD 的已使用寿命约 {percentage_used}%，磨损加快，"
                    "建议减少大文件反复写入并尽早备份。",
                )
        # power_on_hours / 累计读写量只展示不扣分（由 UI / 报告负责展示）

    # ---- 6) 事件日志（最近 30 天） ----
    if error_events >= 20:
        deduct(40, f"过去 30 天系统日志记录了 {error_events} 条与这块盘相关的错误/警告，磁盘可能正在持续出错，请立即备份数据并排查。")
    elif error_events >= 8:
        deduct(25, f"过去 30 天系统日志记录了 {error_events} 条与这块盘相关的错误/警告，建议重点观察，尽早备份数据。")
    elif error_events >= 3:
        deduct(15, f"过去 30 天系统日志记录了 {error_events} 条与这块盘相关的错误/警告，例如：{recent_events[0].get('message', '') if recent_events else '磁盘错误'}")
    elif error_events >= 1:
        sample = recent_events[0].get("message", "") if recent_events else ""
        deduct(8, f"过去 30 天系统日志记录了 {error_events} 条与这块盘相关的错误/警告" + (f"，例如：{sample}" if sample else "") + "。")

    # ---- 7) 卷损坏位 ----
    if dirty_volumes:
        letters = "、".join(str(v.get("drive") or "?") for v in dirty_volumes)
        deduct(40, f"分区 {letters} 被系统标记为「损坏位」已置位，文件系统可能存在损坏，建议尽快备份数据，并使用系统自带的磁盘检查工具修复。")

    # ---- 汇总 ----
    score = int(round(max(0.0, min(100.0, score))))
    if score >= 80:
        level = LEVEL_HEALTHY
    elif score >= 50:
        level = LEVEL_WARNING
    else:
        level = LEVEL_DANGER

    # ---- 硬性结论钳制（优先级高于普通扣分档位） ----
    if force_danger:
        # 系统已报告 Unhealthy：无论得分多少，一律强制「危险」档。
        score = min(score, 49)
        level = LEVEL_DANGER
    elif force_warning and score >= 80:
        # 存在待映射扇区：任何非零 C5 都不允许显示绿色健康，至少「警告」档。
        score = 79
        level = LEVEL_WARNING

    if not reasons:
        reasons.append("各项关键指标均在正常范围内，当前状态良好，请继续保持定期备份的好习惯。")

    # 已有 NVMe 健康数据（或计数器 / SMART 任一通道可用）时不提示数据受限
    if nvme_health is None and not had_counters and not had_smart:
        reasons.insert(0, "部分检测项无法读取（可能未以管理员身份运行或系统不支持），结果可能不完整，仅供参考。")

    return {
        "score": score,
        "level": level,
        "level_text": LEVEL_TEXT[level],
        "reasons": reasons,
    }


def summarize(results: list[dict]) -> dict:
    """汇总多块盘的检测结果，供概览卡与报告使用。

    Args:
        results: 每项需含 "verdict" 字段（evaluate_disk 的返回值）。

    Returns:
        {"total": n, "healthy": n, "warning": n, "danger": n}
    """
    counts = {"total": len(results), "healthy": 0, "warning": 0, "danger": 0}
    for result in results:
        verdict_data = result.get("verdict") or {}
        level = verdict_data.get("level")
        if level in counts:
            counts[level] += 1
    return counts
