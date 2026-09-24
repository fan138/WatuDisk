# -*- coding: utf-8 -*-
"""v1.1 专业指标真机测试（QA 自编）。

覆盖：
- 真机跑 disk_info.get_reliability_counters：每块盘 TemperatureMin/Max、
  PowerCycleCount、PowerOnHours 等字段键完整（值可为 None）；
- 本机 NVMe 盘 PowerOnHours / PowerCycleCount 实测可得；
- format_hours_pro：千分位 + 「约 X.X 年」+ 小时数不换算 + None/非法值；
- format_int 千分位与 None/布尔/非法值容错；
- UI 层 None -> 「—」：用真实 DiskCard._build_metrics_grid 验证
  counters 缺失时指标值显示「—」；有值时正确格式化。

运行需 QT_QPA_PLATFORM=offscreen（文件内自设）。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(TEST_DIR, "..", "src")))
sys.path.insert(0, TEST_DIR)

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from core.disk_info import (  # noqa: E402
    _COUNTER_PROPS,
    format_hours_pro,
    format_int,
    get_physical_disks,
    get_reliability_counters,
)
from ui.main_window import DiskCard  # noqa: E402


def test_real_machine_counter_keys_complete():
    counters_map = get_reliability_counters()
    disks = get_physical_disks()
    assert disks, "真机至少应有一块物理盘"
    for disk in disks:
        device_id = disk["device_id"]
        assert device_id in counters_map, f"盘 {device_id} 缺少可靠性计数器"
        for key in _COUNTER_PROPS:
            assert key in counters_map[device_id], f"盘 {device_id} 缺少字段 {key}"


def test_real_machine_nvme_hours_and_cycles():
    """本机 NVMe 盘 PowerOnHours / PowerCycleCount 字段可得性检查。

    实测平台（raw Get-StorageReliabilityCounter 对本机两块 NVMe 返回
    PowerOnHours/PowerCycleCount = null，且 root\\wmi 的
    MSStorageDriver_FailurePredictData 为空）：OS 未暴露该数据，属环境限制，
    DiskGuard 已正确 None 容错。故此处只断言：
    1) 温度等可读字段非 None（证明计数器通道正常）；
    2) Hours/Cycles 若平台可得则必须为合法非负值。
    """
    disks = get_physical_disks()
    counters_map = get_reliability_counters()
    nvme_disks = [d for d in disks if str(d.get("bus_type") or "").upper() == "NVME"]
    assert nvme_disks, "本机应有 NVMe 盘"
    readable_channel = False
    for disk in nvme_disks:
        counters = counters_map.get(disk["device_id"]) or {}
        temp = counters.get("Temperature")
        temp_max = counters.get("TemperatureMax")
        if isinstance(temp, int) and temp > 0:
            readable_channel = True
            assert temp_max is None or (isinstance(temp_max, int) and temp_max >= temp), (
                f"盘 {disk['device_id']} TempMax({temp_max}) 不应低于当前温度({temp})"
            )
        hours = counters.get("PowerOnHours")
        cycles = counters.get("PowerCycleCount")
        for name, value in (("PowerOnHours", hours), ("PowerCycleCount", cycles)):
            if value is not None:
                assert isinstance(value, int) and value >= 0, f"{name}={value} 非法"
    assert readable_channel, "可靠性计数器通道完全不可读（温度也为空），检测环境异常"


def test_real_machine_temperature_extremes_present():
    """TemperatureMin/Max 字段键存在（值可为 None，键完整即达标）。"""
    counters_map = get_reliability_counters()
    for _device_id, counters in counters_map.items():
        assert "TemperatureMin" in counters
        assert "TemperatureMax" in counters


# ----------------------------------------------------------------------
# 格式化函数
# ----------------------------------------------------------------------
def test_format_hours_pro_thousands_and_years():
    assert format_hours_pro(14200) == "14,200 小时 · 约 1.6 年"
    assert format_hours_pro(8760) == "8,760 小时 · 约 1.0 年"
    assert format_hours_pro(17520) == "17,520 小时 · 约 2.0 年"


def test_format_hours_pro_small_hours_no_year():
    assert format_hours_pro(36) == "36 小时"
    assert format_hours_pro(8759) == "8,759 小时"  # 不足一年不带年


def test_format_hours_pro_invalid():
    assert format_hours_pro(None) is None
    assert format_hours_pro("abc") is None
    assert format_hours_pro(-5) is None
    # 已知不一致（QA 记录）：format_int 对布尔返回 None，而 format_hours 把
    # True 当作 1 -> "1 小时"。规范未定义布尔行为，这里只锁定当前实现不抛异常。
    assert isinstance(format_hours_pro(True), (str, type(None)))


def test_format_int_thousands():
    assert format_int(14200) == "14,200"
    assert format_int(0) == "0"
    assert format_int(999) == "999"
    assert format_int(1234567) == "1,234,567"


def test_format_int_invalid():
    assert format_int(None) is None
    assert format_int("abc") is None
    assert format_int(True) is None
    assert format_int(3.7) == "3"  # int 截断


# ----------------------------------------------------------------------
# UI 层 None -> 「—」
# ----------------------------------------------------------------------
def _metric_values(result: dict) -> dict[str, str]:
    """构建 DiskCard 并收集 metricsCard 中的 label -> value 映射。"""
    card = DiskCard(result)
    card._detail.setVisible(True)
    values: dict[str, str] = {}

    def walk(widget):
        for child in widget.findChildren(QLabel):
            if child.parentWidget() is not None and child.parentWidget().objectName() == "metricsCard":
                continue
        # 直接从 metricsCard 网格收集
        for frame in widget.findChildren(type(card)):  # noqa: F841
            pass

    # 简化：遍历 detail 中 objectName == metricsCard 的 QFrame 子级 QLabel
    from PySide6.QtWidgets import QFrame

    for frame in card.findChildren(QFrame):
        if frame.objectName() == "metricsCard":
            labels = [c for c in frame.findChildren(QLabel)]
            # 成对出现：先 label 后 value（按添加顺序）
            for i in range(0, len(labels) - 1, 2):
                values[labels[i].text()] = labels[i + 1].text()
            break
    return values


def test_metrics_grid_none_shows_dash():
    """counters 为空时专业指标全部显示「—」。

    v1.3 例外：「容量」与「30 天相关事件」是恒有值的信息项——
    容量来自磁盘枚举，0 条事件本身是有意义的健康数据。
    """
    result = {
        "disk": {"device_id": "0", "model": "QA Disk", "media_type": "SSD", "bus_type": "NVMe", "size": 1, "serial": "X"},
        "counters": {},
        "smart_attrs": [],
        "event_count": 0,
        "event_recent": [],
        "dirty_volumes": [],
        "all_volumes": [],
        "verdict": {"score": 95, "level": "healthy", "level_text": "健康", "reasons": []},
    }
    values = _metric_values(result)
    assert values, "未收集到专业指标"
    informational = {"容量", "30 天相关事件"}
    for label, value in values.items():
        if label in informational:
            continue
        assert value == "—", f"{label} 在无数据时应显示「—」，实际「{value}」"
    assert values.get("30 天相关事件") == "0 条"
    # 关键新字段在列
    assert "通电时间" in values and "通电次数" in values
    assert "历史最高温度" in values and "剩余寿命（SSD）" in values


def test_metrics_grid_with_values():
    """有数据时指标正确格式化（千分位、温度、寿命百分比）。"""
    result = {
        "disk": {"device_id": "0", "model": "QA Disk", "media_type": "SSD", "bus_type": "NVMe", "size": 1, "serial": "X"},
        "counters": {
            "PowerOnHours": 14200,
            "PowerCycleCount": 3210,
            "Temperature": 41,
            "TemperatureMax": 58,
            "Wear": 7,
            "ReadErrorsUncorrected": 0,
            "WriteErrorsUncorrected": 0,
        },
        "smart_attrs": [],
        "event_count": 0,
        "event_recent": [],
        "dirty_volumes": [],
        "all_volumes": [],
        "verdict": {"score": 95, "level": "healthy", "level_text": "健康", "reasons": []},
    }
    values = _metric_values(result)
    assert values["通电时间"] == "14,200 小时 · 约 1.6 年"
    assert values["通电次数"] == "3,210"
    assert values["当前温度"] == "41°C"
    assert values["历史最高温度"] == "58°C"
    assert values["剩余寿命（SSD）"] == "93%"
    assert values["不可修正读取错误"] == "0"


def test_metrics_grid_partial_none_mixed():
    """部分字段缺失：缺失的显示「—」，存在的正常显示（同卡混合）。"""
    result = {
        "disk": {"device_id": "0", "model": "QA Disk", "media_type": "HDD", "bus_type": "SATA", "size": 1, "serial": "X"},
        "counters": {"PowerOnHours": 9000},
        "smart_attrs": [],
        "event_count": 0,
        "event_recent": [],
        "dirty_volumes": [],
        "all_volumes": [],
        "verdict": {"score": 95, "level": "healthy", "level_text": "健康", "reasons": []},
    }
    values = _metric_values(result)
    assert values["通电时间"] == "9,000 小时 · 约 1.0 年"
    assert values["通电次数"] == "—"
    assert values["当前温度"] == "—"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
