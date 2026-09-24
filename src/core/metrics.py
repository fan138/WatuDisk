# -*- coding: utf-8 -*-
"""专业指标阈值评估（v1.3）：把每项指标换算成 0-3 警示等级与颜色。

等级约定：
  LEVEL_OK    = 0  正常（默认深色文字，不干扰）
  LEVEL_CAUTION = 1 注意（黄）
  LEVEL_WARN    = 2 警告（橙）
  LEVEL_DANGER  = 3 危险（红）

阈值与评分引擎（verdict.py）的扣分逻辑保持同向：评分里扣分越狠的项，
这里的颜色也越红。信息类指标（通电时间、读写量等）恒为 LEVEL_OK——
它们只是「档案数据」，不反映好坏，不做颜色警示。

忽略语义：被用户忽略的项在 UI 上显示为健康绿色 ✓（只影响显示，
不影响评分——分数永远诚实）。
"""
from __future__ import annotations

from core.disk_info import format_hours_pro, format_int, format_size
from core.nvme_health import format_data_units

LEVEL_OK = 0
LEVEL_CAUTION = 1
LEVEL_WARN = 2
LEVEL_DANGER = 3

# 文字警示色（浅色主题下可读性校准过）
LEVEL_TEXT_COLORS = {
    LEVEL_OK: "",                      # 默认色（theme.metricValue）
    LEVEL_CAUTION: "#B45309",          # 黄-棕
    LEVEL_WARN: "#DD6B1D",             # 橙
    LEVEL_DANGER: "#C93A3A",           # 红
}
LEVEL_IGNORED_COLOR = "#1FAF52"        # 忽略后显示的健康绿


def level_for(key: str, value: object, ctx: dict | None = None) -> int:
    """按指标 key 与数值返回警示等级；信息类 / 缺失恒为 LEVEL_OK。"""
    if value is None:
        return LEVEL_OK
    ctx = ctx or {}
    try:
        v = float(value)
    except (TypeError, ValueError):
        return LEVEL_OK

    if key == "current_temp":
        if v >= 70:
            return LEVEL_DANGER
        if v >= 65:
            return LEVEL_WARN
        if v >= 55:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "max_temp":
        if v >= 90:
            return LEVEL_WARN
        if v >= 80:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "life_remaining":
        if v <= 10:
            return LEVEL_DANGER
        if v <= 20:
            return LEVEL_WARN
        if v <= 40:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "pct_used":
        if v >= 90:
            return LEVEL_DANGER
        if v >= 80:
            return LEVEL_WARN
        if v >= 60:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "spare":
        threshold = ctx.get("spare_threshold")
        try:
            threshold_f = float(threshold) if threshold is not None else 10.0
        except (TypeError, ValueError):
            threshold_f = 10.0
        if v < threshold_f:
            return LEVEL_DANGER
        if v < 20:
            return LEVEL_WARN
        if v < 30:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "media_errors":
        return LEVEL_DANGER if v > 0 else LEVEL_OK
    if key == "critical_warning":
        return LEVEL_DANGER if v > 0 else LEVEL_OK
    if key == "unsafe_shutdowns":
        if v >= 300:
            return LEVEL_WARN
        if v >= 100:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key in ("uncorrected_read", "uncorrected_write"):
        return LEVEL_DANGER if v > 0 else LEVEL_OK
    if key in ("reallocated",):        # 05 重映射扇区
        if v > 0:
            return LEVEL_CAUTION if v < 100 else LEVEL_WARN
        return LEVEL_OK
    if key in ("pending_sector",):     # C5 待映射
        return LEVEL_WARN if v > 0 else LEVEL_OK
    if key in ("uncorrectable",):      # C6 无法修正
        return LEVEL_DANGER if v > 0 else LEVEL_OK
    if key in ("crc_errors",):         # C7 接口错误
        if v >= 1000:
            return LEVEL_WARN
        if v >= 100:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "event_count":
        if v >= 20:
            return LEVEL_DANGER
        if v >= 8:
            return LEVEL_WARN
        if v >= 1:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "free_space":
        if v < 5:
            return LEVEL_DANGER
        if v < 10:
            return LEVEL_WARN
        if v < 20:
            return LEVEL_CAUTION
        return LEVEL_OK
    if key == "dirty_volume":
        return LEVEL_DANGER if v else LEVEL_OK
    # 信息类：power_on_hours / power_cycles / read_written / load_unload /
    # start_stop / total_read / total_written / error_log_entries
    return LEVEL_OK


def metric_items_for_result(result: dict) -> list[dict]:
    """把一次检测结果展开成专业指标列表（UI 渲染与测试共用）。

    Returns:
        [{key, label, text, level, ignore_ctx}]，text 已格式化；
        取不到的字段 text 为「—」且 level=LEVEL_OK。
    """
    counters = result.get("counters") or {}
    attrs = result.get("smart_attrs") or []
    nvme = result.get("nvme_health") or {}
    items: list[dict] = []

    def add(key: str, label: str, text: object, level: int = LEVEL_OK,
            ignore_ctx: dict | None = None) -> None:
        items.append({
            "key": key,
            "label": label,
            "text": str(text) if text not in (None, "") else "—",
            "level": level if text not in (None, "") else LEVEL_OK,
            "ignore_ctx": ignore_ctx or {},
        })

    def first(*values: object) -> object:
        for value in values:
            if value is not None:
                return value
        return None

    # 通电时间 / 次数（信息类）
    hours = first(counters.get("PowerOnHours"), nvme.get("power_on_hours"))
    add("power_on_hours", "通电时间", format_hours_pro(hours) if hours is not None else None)
    cycles = first(counters.get("PowerCycleCount"), nvme.get("power_cycles"))
    add("power_cycles", "通电次数", format_int(cycles))
    add("load_unload", "加载/卸载循环", format_int(counters.get("LoadUnloadCycleCount")) if counters else None)
    add("start_stop", "主轴启停次数", format_int(counters.get("StartStopCycleCount")) if counters else None)

    # 剩余寿命 / 使用率（互为镜像，避免同一事实重复警示）
    wear = counters.get("Wear") if counters else None
    nvme_pct = nvme.get("percentage_used")
    if isinstance(wear, int) and 0 <= wear <= 100:
        life = max(0, 100 - wear)
        add("life_remaining", "剩余寿命（SSD）", f"{life}%", level_for("life_remaining", life))
    elif isinstance(nvme_pct, int) and 0 <= nvme_pct <= 100:
        life = max(0, 100 - nvme_pct)
        add("life_remaining", "剩余寿命（SSD）", f"{life}%", level_for("life_remaining", life))
        add("pct_used", "使用率（NVMe）", f"{nvme_pct}%", level_for("pct_used", nvme_pct))
    else:
        add("life_remaining", "剩余寿命（SSD）", None)
        add("pct_used", "使用率（NVMe）", f"{nvme_pct}%" if isinstance(nvme_pct, int) else None)

    # 温度
    temp = counters.get("Temperature") if counters else None
    if not (isinstance(temp, int) and temp > 0):
        nvme_temp = nvme.get("temperature_c")
        if isinstance(nvme_temp, int) and nvme_temp > -100:
            temp = nvme_temp
    add("current_temp", "当前温度", f"{temp}°C" if isinstance(temp, int) and temp > 0 else None,
        level_for("current_temp", temp))
    temp_max = counters.get("TemperatureMax") if counters else None
    add("max_temp", "历史最高温度", f"{temp_max}°C" if isinstance(temp_max, int) and temp_max > 0 else None,
        level_for("max_temp", temp_max))

    # 错误类（OS 通道）
    add("uncorrected_read", "不可修正读取错误", format_int(counters.get("ReadErrorsUncorrected")) if counters else None,
        level_for("uncorrected_read", counters.get("ReadErrorsUncorrected")))
    add("uncorrected_write", "不可修正写入错误", format_int(counters.get("WriteErrorsUncorrected")) if counters else None,
        level_for("uncorrected_write", counters.get("WriteErrorsUncorrected")))
    add("total_read_errors", "累计读取错误", format_int(counters.get("ReadErrorsTotal")) if counters else None)
    add("total_write_errors", "累计写入错误", format_int(counters.get("WriteErrorsTotal")) if counters else None)

    # NVMe 直读通道
    add("total_written", "累计写入量", format_data_units(nvme.get("data_units_written")))
    add("total_read", "累计读取量", format_data_units(nvme.get("data_units_read")))
    spare = nvme.get("available_spare_pct")
    if isinstance(spare, int):
        threshold = nvme.get("spare_threshold")
        threshold_text = f"（阈值 {threshold}%）" if threshold is not None else ""
        add("spare", "可用备用空间", f"{spare}%{threshold_text}",
            level_for("spare", spare, {"spare_threshold": threshold}))
    else:
        add("spare", "可用备用空间", None)
    add("unsafe_shutdowns", "不安全断电次数", format_int(nvme.get("unsafe_shutdowns")),
        level_for("unsafe_shutdowns", nvme.get("unsafe_shutdowns")))
    add("media_errors", "媒体错误数", format_int(nvme.get("media_errors")),
        level_for("media_errors", nvme.get("media_errors")))

    # SATA SMART 属性
    if attrs:
        raw_map: dict[int, int | None] = {}
        for attr in attrs:
            try:
                raw_map[int(attr.get("id") or 0)] = int(attr.get("raw") or 0)
            except (TypeError, ValueError):
                continue
        add("reallocated", "重映射扇区", format_int(raw_map.get(0x05)),
            level_for("reallocated", raw_map.get(0x05)))
        add("pending_sector", "待映射扇区", format_int(raw_map.get(0xC5)),
            level_for("pending_sector", raw_map.get(0xC5)))
        add("uncorrectable", "无法修正扇区", format_int(raw_map.get(0xC6)),
            level_for("uncorrectable", raw_map.get(0xC6)))
        add("crc_errors", "接口错误（CRC）", format_int(raw_map.get(0xC7)),
            level_for("crc_errors", raw_map.get(0xC7)))

    # 事件日志数量（与详情区事件摘要联动）
    add("event_count", "30 天相关事件", str(result.get("event_count") or 0) + " 条",
        level_for("event_count", result.get("event_count") or 0))

    # 磁盘剩余空间（v1.4：取该盘关联卷中最紧张的一个作为代表）
    worst_volume: dict = {}
    for volume in result.get("all_volumes") or []:
        pct = volume.get("free_pct")
        if isinstance(pct, (int, float)) and (not worst_volume or pct < worst_volume.get("free_pct", 100.0)):
            worst_volume = volume
    if worst_volume:
        free_gb = (worst_volume.get("free") or 0) / 1024 ** 3
        add(
            "free_space",
            "剩余空间",
            f"{worst_volume.get('drive')} {worst_volume.get('free_pct')}%（剩 {free_gb:.0f} GB）",
            level_for("free_space", worst_volume.get("free_pct")),
        )
    else:
        add("free_space", "剩余空间", None)

    # 容量信息（信息类，放最后）
    disk = result.get("disk") or {}
    add("capacity", "容量", format_size(disk.get("size")))
    return items
