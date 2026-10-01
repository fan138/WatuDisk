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

忽略语义（v1.1.1）：被用户忽略的项不再参与评分（评分回归剩余项的真实
水平），但此处的颜色警示仍保留——给用户「自我安慰」的空间，也不掩盖
事实。verdict.evaluate_disk 通过 ignored_keys 参数实现不扣分。
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

    # v1.1.1：SMART 属性原始值兜底表——counters / NVMe 通道缺项时补位，
    # 尽量少显示「—」（论坛反馈：SMART 明细里有数，指标表却是「—」）。
    smart_raw: dict[int, int] = {}
    for attr in attrs:
        try:
            smart_raw[int(attr.get("id") or 0)] = int(attr.get("raw") or 0)
        except (TypeError, ValueError):
            continue

    def _lba_size_text(raw: object) -> str | None:
        """0xF1/0xF2 原始值（LBA 数 ×512 字节）转容量文本；过小视为单位异常，宁缺毋滥。"""
        try:
            total = int(raw) * 512
        except (TypeError, ValueError):
            return None
        if total < 1024 ** 3:
            return None
        tb = total / 1024 ** 4
        return f"{tb:.2f} TB" if tb >= 1 else f"{total / 1024 ** 3:.0f} GB"

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

    # 通电时间 / 次数（信息类；counters → NVMe → SMART 属性三级兜底）
    hours = first(counters.get("PowerOnHours"), nvme.get("power_on_hours"), smart_raw.get(0x09))
    add("power_on_hours", "通电时间", format_hours_pro(hours) if hours is not None else None)
    cycles = first(counters.get("PowerCycleCount"), nvme.get("power_cycles"), smart_raw.get(0x0C))
    add("power_cycles", "通电次数", format_int(cycles))
    # v1.1.1：机械/ SATA 概念字段——无数据时整行隐藏（比「—」更干净）
    load_unload = first(counters.get("LoadUnloadCycleCount"), smart_raw.get(0xC1))
    if load_unload is not None:
        add("load_unload", "加载/卸载循环", format_int(load_unload))
    start_stop = first(counters.get("StartStopCycleCount"), smart_raw.get(0x04))
    if start_stop is not None:
        add("start_stop", "主轴启停次数", format_int(start_stop))

    # 剩余寿命 / 使用率（互为镜像，避免同一事实重复警示；无磨损数据时整行隐藏）
    wear = counters.get("Wear") if counters else None
    nvme_pct = nvme.get("percentage_used")
    if isinstance(wear, int) and 0 <= wear <= 100:
        life = max(0, 100 - wear)
        add("life_remaining", "剩余寿命（SSD）", f"{life}%", level_for("life_remaining", life))
    elif isinstance(nvme_pct, int) and 0 <= nvme_pct <= 100:
        life = max(0, 100 - nvme_pct)
        add("life_remaining", "剩余寿命（SSD）", f"{life}%", level_for("life_remaining", life))
        add("pct_used", "使用率（NVMe）", f"{nvme_pct}%", level_for("pct_used", nvme_pct))

    # 温度（counters → NVMe → SMART 0xC2 原始值兜底；仅接受合理摄氏度区间）
    temp = counters.get("Temperature") if counters else None
    if not (isinstance(temp, int) and temp > 0):
        nvme_temp = nvme.get("temperature_c")
        if isinstance(nvme_temp, int) and nvme_temp > -100:
            temp = nvme_temp
    if not (isinstance(temp, int) and temp > 0):
        c2 = smart_raw.get(0xC2)
        if isinstance(c2, int) and 0 < c2 <= 120:
            temp = c2
    add("current_temp", "当前温度", f"{temp}°C" if isinstance(temp, int) and temp > 0 else None,
        level_for("current_temp", temp))
    temp_max = counters.get("TemperatureMax") if counters else None
    if not (isinstance(temp_max, int) and temp_max > 0):
        # v1.1.1：部分盘 0xC2 原始值按字节打包（低字节当前温 / 高字节历史最高）
        c2_packed = smart_raw.get(0xC2)
        if isinstance(c2_packed, int) and c2_packed > 0xFF:
            packed_max = (c2_packed >> 24) & 0xFF
            if 0 < packed_max <= 120 and (not isinstance(temp, int) or packed_max >= temp):
                temp_max = packed_max
    if isinstance(temp_max, int) and temp_max > 0:
        add("max_temp", "历史最高温度", f"{temp_max}°C", level_for("max_temp", temp_max))
    # 无极值数据时整行隐藏（SMART 0xC2 仅报单字节当前温的盘没有此项）

    # 错误类（OS 通道；系统未提供时整行隐藏——SMART 无对应项，不造假数据）
    for _key, _label, _counter_key in (
        ("uncorrected_read", "不可修正读取错误", "ReadErrorsUncorrected"),
        ("uncorrected_write", "不可修正写入错误", "WriteErrorsUncorrected"),
        ("total_read_errors", "累计读取错误", "ReadErrorsTotal"),
        ("total_write_errors", "累计写入错误", "WriteErrorsTotal"),
    ):
        _value = counters.get(_counter_key)
        if _value is not None:
            add(_key, _label, format_int(_value), level_for(_key, _value))

    # NVMe 直读通道（写入/读取量在 NVMe 缺数据时用 SMART 0xF1/0xF2 兜底；
    # 原始值过小按 LBA 换算不合理时，展示厂商单位原始计数而非「—」）
    written_text = format_data_units(nvme.get("data_units_written"))
    if written_text is None and 0xF1 in smart_raw:
        written_text = _lba_size_text(smart_raw[0xF1]) or f"{smart_raw[0xF1]:,}（厂商单位）"
    if written_text:
        add("total_written", "累计写入量", written_text)
    read_text = format_data_units(nvme.get("data_units_read"))
    if read_text is None and 0xF2 in smart_raw:
        read_text = _lba_size_text(smart_raw[0xF2]) or f"{smart_raw[0xF2]:,}（厂商单位）"
    if read_text:
        add("total_read", "累计读取量", read_text)
    spare = nvme.get("available_spare_pct")
    if isinstance(spare, int):
        threshold = nvme.get("spare_threshold")
        threshold_text = f"（阈值 {threshold}%）" if threshold is not None else ""
        add("spare", "可用备用空间", f"{spare}%{threshold_text}",
            level_for("spare", spare, {"spare_threshold": threshold}))
    else:
        # v1.1.1：SATA 盘用 SMART 0xE8/0xAA 原始值（0-100 视为百分比）兜底
        spare_smart = first(smart_raw.get(0xE8), smart_raw.get(0xAA))
        if isinstance(spare_smart, int) and 0 <= spare_smart <= 100:
            add("spare", "可用备用空间", f"{spare_smart}%", level_for("spare", spare_smart))
    unsafe = first(nvme.get("unsafe_shutdowns"), smart_raw.get(0xAE), smart_raw.get(0xC0))
    if unsafe is not None:
        add("unsafe_shutdowns", "不安全断电次数", format_int(unsafe),
            level_for("unsafe_shutdowns", unsafe))
    if nvme.get("media_errors") is not None:
        add("media_errors", "媒体错误数", format_int(nvme.get("media_errors")),
            level_for("media_errors", nvme.get("media_errors")))

    # SATA SMART 属性（复用兜底表 smart_raw）
    if attrs:
        add("reallocated", "重映射扇区", format_int(smart_raw.get(0x05)),
            level_for("reallocated", smart_raw.get(0x05)))
        add("pending_sector", "待映射扇区", format_int(smart_raw.get(0xC5)),
            level_for("pending_sector", smart_raw.get(0xC5)))
        add("uncorrectable", "无法修正扇区", format_int(smart_raw.get(0xC6)),
            level_for("uncorrectable", smart_raw.get(0xC6)))
        add("crc_errors", "接口错误（CRC）", format_int(smart_raw.get(0xC7)),
            level_for("crc_errors", smart_raw.get(0xC7)))

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
    # 无卷数据时剩余空间整行隐藏（比「—」更干净）

    # 容量信息（信息类，放最后）
    disk = result.get("disk") or {}
    add("capacity", "容量", format_size(disk.get("size")))
    return items
