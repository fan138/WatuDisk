# -*- coding: utf-8 -*-
"""v1.2.2 性能优化回归测试（采集管线合并 + 失败缓存）。

背景（实测基线，2026-10-18）：
- 完整检测 39.9 秒中 99.9% 在等 9 次 PowerShell 子进程；
- 枚举与计数器分两次执行 Get-PhysicalDisk（各约 5-6 秒）；
- Get-Partition 在本机稳定返回空（管理员下也空），每次白付约 7.5 秒
  必然失败后才走 9.1 秒 WMI 兜底；WMI 分区关联 + 卷空间 = 3 次冷启动。

本文件守护三项优化（功能零变更：输出结构、接口签名、兜底链路全部不变）：
A. get_disks_with_counters：一条命令同时取枚举 + 计数器；
B. Get-Partition 失败结论当日缓存（次日自动重置，环境修复能自愈）；
C. WMI 通道下分区关联 + 卷空间合并为一次调用（分隔符分段 JSON）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

import core.disk_info as disk_info  # noqa: E402
import core.store as store_mod  # noqa: E402
import core.volume_check as volume_check  # noqa: E402
from core.store import Store  # noqa: E402

_UI_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "ui"))
_SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
with open(os.path.join(_UI_PATH, "main_window.py"), "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()
with open(os.path.join(_SRC_DIR, "core", "volume_check.py"), "r", encoding="utf-8") as _fh:
    VOLUME_SRC = _fh.read()

_SEP = volume_check._MERGE_SEP

# 合成主通道数据：枚举属性 + 计数器属性合一（两条原命令的字段并集）
_SAMPLE_DISK = {
    "DeviceId": "0",
    "FriendlyName": "合成 SSD",
    "MediaType": "SSD",
    "BusType": "NVMe",
    "HealthStatus": "Healthy",
    "OperationalStatus": "OK",
    "Size": 1000000000000,
    "SerialNumber": "SN-001",
    "FirmwareVersion": "FW9",
    "Temperature": 42,
    "Wear": 3,
    "PowerOnHours": 1200,
    "PowerCycleCount": 88,
    "ReadErrorsUncorrected": 0,
    "WriteErrorsUncorrected": 0,
    "ReadErrorsTotal": 5,
    "WriteErrorsTotal": 7,
    "TemperatureMax": 55,
    "StartStopCycleCount": 12,
    "LoadUnloadCycleCount": 3,
}


def _use_temp_store() -> Store:
    tmp = tempfile.mkdtemp(prefix="diskguard_test_perf_")
    store = Store(tmp)
    store_mod._store = store
    return store


def _reset_store() -> None:
    store_mod._store = None


class _Patch:
    """极简 monkeypatch：with 退出自动还原（不引 pytest 依赖）。"""

    def __init__(self, obj, name, value):
        self.obj = obj
        self.name = name
        self.value = value
        self._orig = None

    def __enter__(self):
        self._orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self._orig)
        return False


# ---------------- A：枚举 + 计数器合并 ----------------

def test_merged_query_is_single_powershell_call():
    """合并后一次检测只发一次 PowerShell（且不触发 WMI 兜底查询）。"""
    calls = {"n": 0}

    def fake_run_ps_json(command, timeout=30):
        calls["n"] += 1
        return [_SAMPLE_DISK]

    fallback_calls = {"n": 0}

    def fake_fallback():
        fallback_calls["n"] += 1
        return {}

    with _Patch(disk_info, "run_ps_json", fake_run_ps_json), \
         _Patch(disk_info, "_fallback_disk_meta", fake_fallback):
        disks, counters = disk_info.get_disks_with_counters()

    assert calls["n"] == 1, f"合并查询应只发 1 次 PowerShell，实际 {calls['n']}"
    assert fallback_calls["n"] == 0, "数据齐全时不应查 WMI 兜底"
    assert len(disks) == 1 and disks[0]["model"] == "合成 SSD"
    assert counters["0"]["Temperature"] == 42 and counters["0"]["Wear"] == 3


def test_merged_output_matches_individual_apis():
    """功能零变更守护：合并输出与分别调用两个原函数逐字段一致。"""
    with _Patch(disk_info, "run_ps_json", lambda command, timeout=30: [_SAMPLE_DISK]):
        disks, counters = disk_info.get_disks_with_counters()
        disks_alone = disk_info.get_physical_disks()
        counters_alone = disk_info.get_reliability_counters()
    assert disks == disks_alone, "合并枚举输出与 get_physical_disks 不一致"
    assert counters == counters_alone, "合并计数器输出与 get_reliability_counters 不一致"
    # 结构抽查：9 个磁盘字段 + 11 个计数器字段
    assert set(disks[0]) == {
        "device_id", "model", "media_type", "bus_type", "health_status",
        "op_status", "size", "serial", "firmware",
    }
    assert set(counters["0"]) == set(disk_info._COUNTER_PROPS)


def test_merged_falls_back_to_cim_when_primary_empty():
    """主通道失败时兜底链路不变：CIM 枚举 + CIM 计数器。"""
    def fake_run_ps_json(command, timeout=30):
        return None

    wmi_disks = [{"device_id": "1", "model": "WMI 盘", "media_type": "HDD", "bus_type": "ATA",
                  "health_status": "Healthy", "op_status": "OK", "size": 1, "serial": "S",
                  "firmware": ""}]
    cim_calls = {"n": 0}

    def fake_cim():
        cim_calls["n"] += 1
        return {"1": {"Temperature": 30}}

    with _Patch(disk_info, "run_ps_json", fake_run_ps_json), \
         _Patch(disk_info, "_enumerate_via_wmi", lambda: wmi_disks), \
         _Patch(disk_info, "_counters_via_cim", fake_cim):
        disks, counters = disk_info.get_disks_with_counters()
    assert disks == wmi_disks, "主通道空应走 CIM 枚举兜底"
    assert cim_calls["n"] == 0, "枚举兜底已成功时不必再查 CIM 计数器"


# ---------------- B：standard 失败当日缓存 ----------------

def test_standard_failure_cached_for_today():
    """当日缓存：standard 失败后，当天再次查询不再重复必然失败的尝试。"""
    store = _use_temp_store()
    try:
        standard_calls = {"n": 0}

        def fake_standard():
            standard_calls["n"] += 1
            return {}

        wmi_calls = {"n": 0}

        def fake_wmi():
            wmi_calls["n"] += 1
            return {"C": [0]}

        with _Patch(volume_check, "_get_partition_map_standard", fake_standard), \
             _Patch(volume_check, "_get_partition_map_wmi", fake_wmi):
            first = volume_check._get_partition_map()
            second = volume_check._get_partition_map()

        assert standard_calls["n"] == 1, f"当天 standard 只应尝试 1 次，实际 {standard_calls['n']}"
        assert wmi_calls["n"] == 2, "两次查询都应落到 WMI 兜底"
        assert first == second == [{"drive": "C", "disk_numbers": [0], "disk_number": 0}]
        assert store.get_setting(volume_check._PARTMAP_STD_FAILED_KEY) == date.today().isoformat()
    finally:
        _reset_store()


def test_standard_failure_cache_resets_next_day():
    """跨日重置：缓存只当天有效，环境修复后次日自动重新尝试 standard。"""
    store = _use_temp_store()
    try:
        store.set_setting(
            volume_check._PARTMAP_STD_FAILED_KEY,
            (date.today() - timedelta(days=1)).isoformat(),
        )
        standard_calls = {"n": 0}

        def fake_standard():
            standard_calls["n"] += 1
            return {"C": [0]}  # 环境已修复

        with _Patch(volume_check, "_get_partition_map_standard", fake_standard), \
             _Patch(volume_check, "_get_partition_map_wmi", lambda: {"D": [9]}):
            result = volume_check._get_partition_map()

        assert standard_calls["n"] == 1, "跨日后应重新尝试 standard"
        assert result == [{"drive": "C", "disk_numbers": [0], "disk_number": 0}], \
            "standard 恢复后应使用其结果"
        assert store.get_setting(volume_check._PARTMAP_STD_FAILED_KEY) != date.today().isoformat(), \
            "standard 成功时不应写失败缓存"
    finally:
        _reset_store()


def test_standard_success_not_cached():
    """standard 成功时不写任何缓存设置（不改变原有成功路径行为）。"""
    store = _use_temp_store()
    try:
        with _Patch(volume_check, "_get_partition_map_standard", lambda: {"C": [0], "D": [0]}), \
             _Patch(volume_check, "_get_partition_map_wmi", lambda: {}):
            result = volume_check._get_partition_map()
        assert store.get_setting(volume_check._PARTMAP_STD_FAILED_KEY) is None, \
            "standard 成功不应写失败缓存"
        assert [r["drive"] for r in result] == ["C", "D"]
    finally:
        _reset_store()


# ---------------- C：WMI 分区 + 卷空间合并 ----------------

def _merged_sample_text() -> str:
    """构造合并查询的三段式合成输出（分区关联 2 段 + 卷空间 1 段）。"""
    logical = [{
        "antecedent": 'Win32_DiskPartition (DeviceID = "Disk #0, Partition #1")',
        "dependent": 'Win32_LogicalDisk (DeviceID = "C:")',
    }]
    disk = [{
        "antecedent": "\\\\\\\\.\\\\PHYSICALDRIVE0",
        "dependent": 'Win32_DiskPartition (DeviceID = "Disk #0, Partition #1")',
    }]
    volume = [{"DriveLetter": "C", "Size": 100, "SizeRemaining": 40, "FileSystemType": "NTFS"}]
    return (_SEP.join(json.dumps(x) for x in (logical, disk, volume)))


def test_merged_partition_space_parsing():
    """分隔符分段解析：分区 join 与卷空间字段与原通道一致。"""
    with _Patch(volume_check, "run_ps_text", lambda command, timeout=45: _merged_sample_text()):
        grouped, space_map = volume_check._get_partition_and_space_merged()
    assert grouped == {"C": [0]}, f"分区 join 结果不对: {grouped}"
    assert space_map == {
        "C": {"size": 100, "free": 40, "free_pct": 40.0, "fstype": "NTFS"},
    }, f"卷空间解析不对: {space_map}"


def test_merged_query_failure_returns_empty():
    """合并查询失败（命令失败 / 分段数不对）时返回空，由调用方兜底。"""
    for bad in (None, "只有一段", "两" + _SEP + "段"):
        with _Patch(volume_check, "run_ps_text", lambda command, timeout=45, _b=bad: _b):
            grouped, space_map = volume_check._get_partition_and_space_merged()
        assert grouped == {} and space_map == {}, f"失败输入应返回空: {bad!r}"


def test_collect_volume_maps_uses_merged_when_standard_unavailable():
    """standard 不可用时：分区图与卷空间走合并查询（只发一次 PowerShell）。"""
    store = _use_temp_store()
    try:
        ps_json_calls = {"n": 0}
        ps_text_calls = {"n": 0}

        def fake_run_ps_json(command, timeout=30):
            ps_json_calls["n"] += 1
            return None

        def fake_run_ps_text(command, timeout=45):
            ps_text_calls["n"] += 1
            return _merged_sample_text()

        with _Patch(volume_check, "_get_partition_map_standard", lambda: {}), \
             _Patch(volume_check, "run_ps_json", fake_run_ps_json), \
             _Patch(volume_check, "run_ps_text", fake_run_ps_text):
            grouped, space_map = volume_check._collect_volume_maps()

        assert grouped == {"C": [0]} and space_map["C"]["free_pct"] == 40.0
        assert ps_text_calls["n"] == 1, "合并查询应只发 1 次 PowerShell"
        assert ps_json_calls["n"] == 0, "standard 被 patch 跳过，合并路径不应再发 JSON 查询"
    finally:
        _reset_store()


def test_collect_volume_maps_standard_path_unchanged():
    """standard 可用时：与原逻辑相同，分区图与卷空间各查各的（不走合并）。"""
    store = _use_temp_store()
    try:
        merged_calls = {"n": 0}

        def fake_merged():
            merged_calls["n"] += 1
            return {}, {}

        with _Patch(volume_check, "_get_partition_map_standard", lambda: {"C": [0]}), \
             _Patch(volume_check, "_get_volume_space",
                    lambda: {"C": {"size": 10, "free": 5, "free_pct": 50.0, "fstype": "NTFS"}}), \
             _Patch(volume_check, "_get_partition_and_space_merged", fake_merged):
            grouped, space_map = volume_check._collect_volume_maps()

        assert merged_calls["n"] == 0, "standard 可用时不应走合并查询"
        assert grouped == {"C": [0]} and space_map["C"]["free_pct"] == 50.0
    finally:
        _reset_store()


def test_check_volumes_output_shape_unchanged():
    """check_volumes 输出结构（字段 / 冒号 / 排序）与优化前一致。"""
    with _Patch(volume_check, "_collect_volume_maps",
                lambda: ({"C": [0], "D": [0, 1]},
                         {"C": {"size": 100, "free": 90, "free_pct": 90.0, "fstype": "NTFS"},
                          "D": {"size": 200, "free": 20, "free_pct": 10.0, "fstype": "exFAT"}})), \
         _Patch(volume_check, "_query_dirty", lambda letter: letter == "D"):
        volumes = volume_check.check_volumes()
    assert volumes == [
        {"drive": "C:", "dirty": False, "disk_number": 0, "disk_numbers": [0],
         "size": 100, "free": 90, "free_pct": 90.0, "fstype": "NTFS"},
        {"drive": "D:", "dirty": True, "disk_number": 0, "disk_numbers": [0, 1],
         "size": 200, "free": 20, "free_pct": 10.0, "fstype": "exFAT"},
    ]


# ---------------- 接线层：源码守卫 ----------------

def test_detect_uses_merged_pipeline():
    """主检测流程必须走合并通道（否则优化不生效）。"""
    detect_start = UI_SRC.index("def _detect")
    detect_body = UI_SRC[detect_start:UI_SRC.index("class DetectStepsWidget", detect_start)]
    assert "get_disks_with_counters()" in detect_body, "_detect 未使用合并查询"
    assert "get_reliability_counters()" not in detect_body, \
        "_detect 仍在单独调用计数器（合并优化未接线）"
    assert "def check_volumes(" in VOLUME_SRC and "_collect_volume_maps()" in VOLUME_SRC, \
        "check_volumes 未接合并入口"


def test_public_apis_preserved():
    """功能零变更：原公开函数与内部通道全部保留（测试与真机 QA 直接调用）。"""
    disk_src = open(os.path.join(_SRC_DIR, "core", "disk_info.py"), encoding="utf-8").read()
    for name in (
        "def get_physical_disks(",
        "def get_reliability_counters(",
        "def get_disks_with_counters(",
    ):
        assert name in disk_src, f"disk_info 缺少 {name}"
    for name in (
        "def _get_partition_map_standard(",
        "def _get_partition_map_wmi(",
        "def _get_volume_space(",
        "def _get_partition_map(",
        "def check_volumes(",
    ):
        assert name in VOLUME_SRC, f"volume_check 缺少 {name}（接口被删？）"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
