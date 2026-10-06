# -*- coding: utf-8 -*-
"""v1.2（#12）磁盘枚举双通道兜底回归测试。

坛友 fanny188 实证：Intel NUC11 + Windows 11 IoT Enterprise LTSC 2021，
Get-PhysicalDisk 在应用内隐藏 PowerShell 调用里返回空（手动窗口正常、
StorSvc 也 Running），挖兔于是显示「找不到硬盘」，后续还连锁出现
一串「需要管理员权限」的误报。Win32_DiskDrive 走 CIM、不依赖 Storage
模块，在该环境已验证可正常返回全部磁盘。

修复：把 Win32_DiskDrive 从「仅补型号」升级为真正的主枚举兜底。

关键不变量（全代码库把 device_id 当纯数字字符串用）：
- int(device_id) 取 PhysicalDrive 号（nvme_health 直读）
- 拼 harddisk{n} 匹配事件日志（event_scan）
- 与卷号 str(n) 比对归因（main_window）
因此兜底通道必须沿用 Index 数字作为 device_id。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import disk_info  # noqa: E402

# 模拟 Win32_DiskDrive 在 IoT LTSC 下的真实返回
WMI_PAYLOAD = [
    {
        "Index": 0,
        "Model": "Acer SSD N5000 2TB (SCSI)",
        "SerialNumber": "SN5000TEST",
        "Size": 2147483648000,
        "MediaType": "Fixed hard disk media",
        "Status": "OK",
        "InterfaceType": "SCSI",
        "PNPDeviceID": "SCSI\\DISK&VEN_NVME&PROD_ASTRAL_SUM",
    },
    {
        "Index": 2,
        "Model": "Generic STORAGE DEVICE[USB]",
        "SerialNumber": "USB123",
        "Size": 64000000000,
        "MediaType": "Removable Media",
        "Status": "OK",
        "InterfaceType": "USB",
        "PNPDeviceID": "USBSTOR\\DISK&VEN_GENERIC&PROD_STORAGE",
    },
]


def _with_payload(payload):
    """临时替换 run_ps_json 返回指定数据。"""
    original = disk_info.run_ps_json
    disk_info.run_ps_json = lambda command, timeout=0: payload
    return original


# ---------------- device_id 必须保持纯数字 ----------------

def test_wmi_fallback_device_id_is_plain_number():
    """兜底通道的 device_id 必须是纯数字字符串，否则 NVMe 直读/事件日志/卷归因全断。"""
    orig = _with_payload(WMI_PAYLOAD)
    try:
        disks = disk_info._enumerate_via_wmi()
    finally:
        disk_info.run_ps_json = orig
    assert len(disks) == 2
    for d in disks:
        assert d["device_id"].isdigit(), f"device_id 非纯数字: {d['device_id']!r}"
    assert [d["device_id"] for d in disks] == ["0", "2"]


# ---------------- 型号 / 类型 / 接口识别 ----------------

def test_wmi_fallback_cleans_model_suffix():
    """CIM 常在型号尾部附 (SCSI)/(ATAPI) 噪声，应清理掉。"""
    orig = _with_payload(WMI_PAYLOAD)
    try:
        disks = disk_info._enumerate_via_wmi()
    finally:
        disk_info.run_ps_json = orig
    assert disks[0]["model"] == "Acer SSD N5000 2TB", f"型号未清理: {disks[0]['model']!r}"


def test_wmi_fallback_detects_nvme_as_ssd_not_hdd():
    """回归：CIM 的 MediaType 对 SSD 同样返回 "Fixed hard disk media"，
    若照此判 HDD 会让 is_ssd=False，SSD 专属指标（剩余寿命）整片不显示。"""
    orig = _with_payload(WMI_PAYLOAD)
    try:
        disks = disk_info._enumerate_via_wmi()
    finally:
        disk_info.run_ps_json = orig
    nvme = disks[0]
    assert nvme["media_type"] == "SSD", f"NVMe 盘应判为 SSD，实际 {nvme['media_type']}"
    assert nvme["bus_type"] == "NVME", f"NVMe 盘 bus_type 应为 NVME，实际 {nvme['bus_type']}"


def test_wmi_fallback_detects_usb_device():
    """U 盘 / 移动硬盘应识别为 USB 接口 + Removable。"""
    orig = _with_payload(WMI_PAYLOAD)
    try:
        disks = disk_info._enumerate_via_wmi()
    finally:
        disk_info.run_ps_json = orig
    usb = disks[1]
    assert usb["bus_type"] == "USB", f"USB 设备 bus_type 应为 USB，实际 {usb['bus_type']}"
    assert usb["media_type"] == "Removable", f"U 盘 media_type 应为 Removable，实际 {usb['media_type']}"


def test_wmi_fallback_health_from_status():
    """Status=OK -> Healthy；非 OK 状态原样带出。"""
    payload = [dict(WMI_PAYLOAD[0], Status="Degraded")]
    orig = _with_payload(payload)
    try:
        disks = disk_info._enumerate_via_wmi()
    finally:
        disk_info.run_ps_json = orig
    assert disks[0]["health_status"] == "Degraded"
    assert disks[0]["op_status"] == "Degraded"


# ---------------- 主通道空时自动切兜底 ----------------

def test_get_physical_disks_falls_back_when_primary_empty():
    """核心断言：主通道返回空时，必须改走 CIM 通道，而不是返回 0 块盘。"""
    calls: list[str] = []

    def fake_run(command, timeout=0):
        calls.append(command)
        if "Get-PhysicalDisk" in command:
            return None  # 模拟 IoT LTSC 下 Get-PhysicalDisk 返回空
        if "Win32_DiskDrive" in command:
            return WMI_PAYLOAD
        return None

    original = disk_info.run_ps_json
    disk_info.run_ps_json = fake_run
    try:
        disks = disk_info.get_physical_disks()
    finally:
        disk_info.run_ps_json = original
    assert len(disks) == 2, f"主通道空时应兜底列出 2 块盘，实际 {len(disks)}"
    assert any("Get-PhysicalDisk" in c for c in calls), "应先尝试主通道"
    assert any("Win32_DiskDrive" in c for c in calls), "主通道失败后应尝试 CIM 兜底"


def test_get_physical_disks_keeps_primary_when_available():
    """主通道正常时不得被兜底覆盖（避免改变现有行为）。"""
    primary = [
        {"DeviceId": "0", "FriendlyName": "PrimaryDisk", "MediaType": "SSD",
         "BusType": "NVMe", "HealthStatus": "Healthy", "OperationalStatus": "OK",
         "Size": 1000, "SerialNumber": "SER1"}
    ]

    def fake_run(command, timeout=0):
        if "Get-PhysicalDisk |" in command:
            return primary
        if "Win32_DiskDrive" in command:
            return WMI_PAYLOAD  # 兜底数据不同，若被覆盖即可发现
        return None

    original = disk_info.run_ps_json
    disk_info.run_ps_json = fake_run
    try:
        disks = disk_info.get_physical_disks()
    finally:
        disk_info.run_ps_json = original
    assert len(disks) == 1, f"主通道有效时应只返回 1 块，实际 {len(disks)}"
    assert disks[0]["model"] == "PrimaryDisk", "主通道结果不应被兜底覆盖"


def test_get_physical_disks_returns_empty_when_both_fail():
    """两条通道都失败才返回空列表（保持优雅降级，不抛异常）。"""
    original = disk_info.run_ps_json
    disk_info.run_ps_json = lambda command, timeout=0: None
    try:
        assert disk_info.get_physical_disks() == []
    finally:
        disk_info.run_ps_json = original


# ---------------- 计数器兜底：DeviceId 两种格式都要能取到盘号 ----------------

def test_counters_cim_parses_both_device_id_formats():
    """MSFT_PhysicalDisk 的 DeviceId 两种格式都可能出现：
    纯数字 "0"（部分环境）或 反斜杠 PHYSICALDRIVE2 形式；都要归一为纯数字键。"""
    payload = [
        {"DeviceId": "0", "Temperature": 35, "PowerOnHours": 1000},
        {"DeviceId": "\\\\.\\PHYSICALDRIVE1", "Temperature": 40, "PowerOnHours": 500},
    ]
    orig = _with_payload(payload)
    try:
        result = disk_info._counters_via_cim()
    finally:
        disk_info.run_ps_json = orig
    assert set(result.keys()) == {"0", "1"}, f"键未归一: {list(result.keys())}"
    assert result["0"]["Temperature"] == 35
    assert result["1"]["PowerOnHours"] == 500


def test_counters_cim_fallback_used_when_primary_empty():
    """主通道计数器为空时应走 CIM 兜底（否则「列出了盘却没温度」）。"""
    payload = [{"DeviceId": "0", "Temperature": 36, "PowerOnHours": 400}]
    orig = _with_payload(payload)
    try:
        result = disk_info.get_reliability_counters()
    finally:
        disk_info.run_ps_json = orig
    assert "0" in result, f"计数器主通道空时应兜底，实际 {list(result.keys())}"
    assert result["0"]["Temperature"] == 36


# ---------------- 健壮性 ----------------

def test_wmi_fallback_skips_malformed_rows():
    """混入缺 Index / 非法 Index / 非字典的行应跳过而非崩溃。"""
    payload = [
        {"Model": "NoIndex"},                      # 缺 Index
        {"Index": "bad", "Model": "BadIndex"},      # 非法 Index
        {"Index": -1, "Model": "Negative"},         # 负数
        "junk",                                     # 非字典
        WMI_PAYLOAD[0],
    ]
    orig = _with_payload(payload)
    try:
        disks = disk_info._enumerate_via_wmi()
    finally:
        disk_info.run_ps_json = orig
    assert len(disks) == 1, f"应只保留 1 条有效记录，实际 {len(disks)}"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
