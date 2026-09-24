# -*- coding: utf-8 -*-
"""物理磁盘枚举与可靠性计数器读取（通过 PowerShell）。

数据来源：
- Get-PhysicalDisk：磁盘基础信息；
- Get-StorageReliabilityCounter：温度 / 磨损 / 错误计数 / 通电时间等。
"""
from __future__ import annotations

from core.powershell_runner import run_ps_json

# 用于界面 / 报告显示的类型与接口名映射
BUS_TEXT = {"NVME": "NVMe", "SATA": "SATA", "USB": "USB", "SAS": "SAS", "RAID": "RAID"}

_DISK_PROPS = "FriendlyName, MediaType, BusType, HealthStatus, OperationalStatus, Size, SerialNumber, DeviceId"

# 需要提取的可靠性计数器字段（v1.1 扩展：温度极值 / 通电次数）
_COUNTER_PROPS = (
    "Temperature",
    "TemperatureMin",
    "TemperatureMax",
    "Wear",
    "ReadErrorsUncorrected",
    "WriteErrorsUncorrected",
    "ReadErrorsTotal",
    "WriteErrorsTotal",
    "PowerOnHours",
    "PowerCycleCount",
    "StartStopCycleCount",
    "LoadUnloadCycleCount",
)


def _to_int(value: object) -> int | None:
    """把 PowerShell 输出的数字安全转换为 int，失败返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_size(num_bytes: int | None) -> str:
    """把字节数格式化为 GB / TB 文本。"""
    if not num_bytes or num_bytes <= 0:
        return "未知容量"
    gb = num_bytes / (1024 ** 3)
    if gb >= 1024:
        return f"{gb / 1024:.2f} TB"
    return f"{gb:.0f} GB"


def format_hours(hours: int | None) -> str | None:
    """把通电小时数格式化为人类可读文本；无数据返回 None。"""
    if hours is None:
        return None
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        return None
    if hours < 0:
        return None
    text = f"{hours:,} 小时"
    if hours >= 8760:
        text += f"（约 {hours / 8760:.1f} 年）"
    return text


def format_hours_pro(hours: int | None) -> str | None:
    """专业指标用的通电时间格式：「14,200 小时 · 约 1.6 年」；无数据返回 None。"""
    text = format_hours(hours)
    if text is None:
        return None
    try:
        value = int(hours)  # type: ignore[arg-type]  # format_hours 已校验
    except (TypeError, ValueError):
        return text
    if value < 8760:
        return text
    # 把全角括号版本（约 X 年）替换为「· 约 X 年」的专业软件风格
    return text.replace("（约 ", " · 约 ").replace("）", "")


def format_int(value: object) -> str | None:
    """把数值格式化为千分位字符串；None / 非法值返回 None（界面显示「—」）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return None


def _fallback_disk_meta() -> dict[str, dict]:
    """兼容性兜底（v1.5）：Win32_DiskDrive 的型号/序列号/容量。

    某些 RAID / USB 桥 / 老驱动环境下 Get-PhysicalDisk 的 FriendlyName /
    SerialNumber 为空或 MediaType=Unspecified，用 WMI 经典通道补齐。
    Returns:
        device_id(str) -> {model, serial, size, media_hint}
    """
    command = (
        "Get-CimInstance Win32_DiskDrive | Select-Object Index, Model, SerialNumber, "
        "Size, MediaType, InterfaceType | ConvertTo-Json -Depth 2"
    )
    data = run_ps_json(command, timeout=30)
    result: dict[str, dict] = {}
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        try:
            index = str(int(item.get("Index")))
        except (TypeError, ValueError):
            continue
        media = str(item.get("MediaType") or "")
        result[index] = {
            "model": str(item.get("Model") or "").strip(),
            "serial": str(item.get("SerialNumber") or "").strip(),
            "size": _to_int(item.get("Size")) or 0,
            "media_hint": "HDD" if "externalharddiskmedia" not in media.lower() and "harddiskmedia" in media.lower() else "",
        }
    return result


def get_physical_disks() -> list[dict]:
    """枚举所有物理磁盘。

    Returns:
        磁盘信息列表，每项含 device_id / model / media_type / bus_type /
        health_status / op_status / size / serial；失败返回空列表。
        v1.5：FriendlyName/SerialNumber 缺失时用 Win32_DiskDrive 兜底补齐。
    """
    command = f"Get-PhysicalDisk | Select-Object {_DISK_PROPS} | ConvertTo-Json -Depth 3"
    data = run_ps_json(command, timeout=30)
    if data is None:
        return []
    items = data if isinstance(data, list) else [data]
    fallback = _fallback_disk_meta()
    disks: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        device_id = str(item.get("DeviceId") if item.get("DeviceId") is not None else "")
        model = str(item.get("FriendlyName") or "").strip()
        serial = str(item.get("SerialNumber") or "").strip()
        size = _to_int(item.get("Size")) or 0
        media_type = str(item.get("MediaType") or "Unspecified")
        meta = fallback.get(device_id) or {}
        if (not model or model == "未知型号") and meta.get("model"):
            model = meta["model"]
        if not serial and meta.get("serial"):
            serial = meta["serial"]
        if not size and meta.get("size"):
            size = meta["size"]
        if media_type.lower() in ("", "unspecified", "none") and meta.get("media_hint"):
            media_type = meta["media_hint"]
        disks.append(
            {
                "device_id": device_id,
                "model": model or "未知型号",
                "media_type": media_type,
                "bus_type": str(item.get("BusType") or "Unknown"),
                "health_status": str(item.get("HealthStatus") or "Unknown"),
                "op_status": str(item.get("OperationalStatus") or "Unknown"),
                "size": size,
                "serial": serial,
            }
        )
    return disks


def get_reliability_counters() -> dict[str, dict]:
    """读取所有磁盘的可靠性计数器（温度 / 磨损 / 错误 / 通电时间等）。

    Returns:
        device_id -> 计数器字典（值为 int 或 None）；整体失败返回空字典。
    """
    counter_expr = "; ".join(f"{name} = $c.{name}" for name in _COUNTER_PROPS)
    command = (
        "Get-PhysicalDisk | ForEach-Object { "
        "$c = $_ | Get-StorageReliabilityCounter; "
        "[PSCustomObject]@{ DeviceId = $_.DeviceId; " + counter_expr + " } "
        "} | ConvertTo-Json -Depth 3"
    )
    data = run_ps_json(command, timeout=45)
    if data is None:
        return {}
    items = data if isinstance(data, list) else [data]
    result: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        device_id = str(item.get("DeviceId") if item.get("DeviceId") is not None else "")
        if device_id == "":
            continue
        result[device_id] = {name: _to_int(item.get(name)) for name in _COUNTER_PROPS}
    return result
