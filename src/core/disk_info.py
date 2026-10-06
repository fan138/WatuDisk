# -*- coding: utf-8 -*-
"""物理磁盘枚举与可靠性计数器读取（通过 PowerShell）。

数据来源：
- Get-PhysicalDisk：磁盘基础信息；
- Get-StorageReliabilityCounter：温度 / 磨损 / 错误计数 / 通电时间等。
"""
from __future__ import annotations

import re

from core.powershell_runner import run_ps_json

# v1.2（#12）：CIM 通道的 DeviceId 存在两种格式——部分环境返回纯数字（"0"），
# 部分返回 "\\.\PHYSICALDRIVE2" 形式。两种都要能提取出盘号，
# 使兜底通道的计数器键与主通道的纯数字 device_id 保持一致。
_PHYSICALDRIVE_ID_RE = re.compile(r"^(?:\d+|.*PHYSICALDRIVE(\d+))$", re.IGNORECASE)

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


def _enumerate_via_wmi() -> list[dict]:
    """CIM 主枚举兜底（v1.2 #12）：Get-PhysicalDisk 不可用时改用 Win32_DiskDrive 列盘。

    背景（坛友 fanny188 实证）：Intel NUC11 + Windows 11 IoT Enterprise LTSC 2021
    上，Get-PhysicalDisk 在挖兔应用内的隐藏 PowerShell 调用里**返回空**（用户手动
    在普通窗口跑正常，StorSvc 也是 Running），导致全盘显示 0 块、后续一串
    "需要管理员权限"的连锁误报。Win32_DiskDrive 走 CIM、不依赖 Storage 模块，
    在该环境已验证可正常返回全部磁盘。

    关键约束：全代码库把 device_id 当**纯数字字符串**使用（int(device_id) 取
    PhysicalDrive 号、拼 harddisk{n} 事件日志名、与卷号 str(n) 比对），因此
    兜底通道必须沿用 Index 数字作为 device_id，不得改成反斜杠 PHYSICALDRIVE 形式。

    Returns:
        与 get_physical_disks 同构的磁盘列表；无数据返回空列表。
    """
    command = (
        "Get-CimInstance Win32_DiskDrive | Select-Object Index, Model, SerialNumber, "
        "Size, MediaType, Status, InterfaceType, PNPDeviceID | "
        "ConvertTo-Json -Depth 2"
    )
    data = run_ps_json(command, timeout=30)
    if data is None:
        return []
    items = data if isinstance(data, list) else [data]
    disks: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("Index"))
        except (TypeError, ValueError):
            continue
        if index < 0:
            continue
        model = str(item.get("Model") or "").strip()
        # 去掉 CIM 常在型号尾部附带的 "(ATAPI" / "(SCSI)" 等噪声后缀
        if "(" in model:
            model = model.split("(", 1)[0].strip()
        media_raw = str(item.get("MediaType") or "").lower()
        interface = str(item.get("InterfaceType") or "").lower()
        pnp = str(item.get("PNPDeviceID") or "")
        pnp_lower = pnp.lower()
        # 注意：CIM 的 MediaType 对 SSD 同样返回 "Fixed hard disk media"，
        # 不能据此判 HDD——固态盘必须靠 PNP 标识识别，否则 SSD 专属指标
        # （剩余寿命/磨损）会因 is_ssd 判 False 而整片不显示。
        is_nvme = "nvme" in pnp_lower
        is_sata_ssd = ("\\sata" in pnp_lower or "sata" in pnp_lower) and (
            "ssd" in pnp_lower or "solid" in pnp_lower
        )
        if is_nvme or is_sata_ssd:
            media_type = "SSD"
        elif "removable" in media_raw or "cd-rom" in media_raw:
            media_type = "Removable"
        elif "fixed hard disk media" in media_raw:
            media_type = "HDD"
        elif "removable" in interface:
            media_type = "Removable"
        else:
            media_type = "Unspecified"
        # 接口类型：USB / NVMe / SCSI / ATA，无法判定时留 Unknown 交由后续通道补真值
        if "usb" in interface or "usb" in pnp_lower:
            bus_type = "USB"
        elif is_nvme:
            bus_type = "NVME"
        elif "sas" in pnp_lower or "scsi" in interface or "scsi" in pnp_lower:
            bus_type = "SCSI"
        elif "sata" in pnp_lower or "ata" in interface or "ide" in interface:
            bus_type = "ATA"
        else:
            bus_type = "Unknown"
        status = str(item.get("Status") or "").strip()
        health_status = "Healthy" if status.upper() in ("OK", "") else status
        disks.append(
            {
                "device_id": str(index),
                "model": model or "未知型号",
                "media_type": media_type,
                "bus_type": bus_type,
                "health_status": health_status,
                "op_status": "OK" if health_status == "Healthy" else health_status,
                "size": _to_int(item.get("Size")) or 0,
                "serial": str(item.get("SerialNumber") or "").strip(),
            }
        )
    return disks


def get_physical_disks() -> list[dict]:
    """枚举所有物理磁盘（双通道：Get-PhysicalDisk 优先，CIM 兜底）。

    Returns:
        磁盘信息列表，每项含 device_id / model / media_type / bus_type /
        health_status / op_status / size / serial；两条通道都失败返回空列表。
        v1.5：FriendlyName/SerialNumber 缺失时用 Win32_DiskDrive 兜底补齐。
        v1.2（#12）：主通道返回空时改用 Win32_DiskDrive **主枚举兜底**，
            解决 IoT LTSC / PE 等 Storage 接口不可用环境「找不到硬盘」的问题。
    """
    command = f"Get-PhysicalDisk | Select-Object {_DISK_PROPS} | ConvertTo-Json -Depth 3"
    data = run_ps_json(command, timeout=30)
    disks: list[dict] = []
    if data is not None:
        items = data if isinstance(data, list) else [data]
        fallback = _fallback_disk_meta()
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
    # v1.2（#12）：主通道无有效结果（命令失败 / 返回空 / 全部缺 device_id）时，
    # 改走 CIM 通道列盘，而不是让用户看到「0 块盘」。
    if not any(d.get("device_id") for d in disks):
        wmi_disks = _enumerate_via_wmi()
        if wmi_disks:
            return wmi_disks
    return disks


def _counters_via_cim() -> dict[str, dict]:
    """可靠性计数器的 CIM 兜底（v1.2 #12）。

    Get-PhysicalDisk | Get-StorageReliabilityCounter 依赖 Storage 模块，在
    IoT LTSC / 部分 PE 环境下不可用；改用 WMI 命名空间
    root\\Microsoft\\Windows\\Storage 的 MSFT_PhysicalDisk，
    它提供同一套可靠性计数器且不依赖 Get-PhysicalDisk cmdlet。

    Returns:
        device_id(数字字符串) -> 计数器字典；失败返回空字典。
    """
    counter_expr = "; ".join(f"{name} = $c.{name}" for name in _COUNTER_PROPS)
    # 用 DeviceId 属性（形如 "\\.\PHYSICALDRIVE0"）反推盘号，保持与主通道一致的键
    command = (
        "Get-CimInstance -Namespace root/Microsoft/Windows/Storage "
        "-ClassName MSFT_PhysicalDisk -ErrorAction SilentlyContinue | "
        "ForEach-Object { $c = $_; "
        "[PSCustomObject]@{ DeviceId = $c.DeviceId; " + counter_expr + " } } | "
        "ConvertTo-Json -Depth 3"
    )
    data = run_ps_json(command, timeout=45)
    if data is None:
        return {}
    items = data if isinstance(data, list) else [data]
    result: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("DeviceId") or "")
        # DeviceId 两种格式都要兼容：纯数字 "2" 或 反斜杠 PHYSICALDRIVE2 形式
        match = _PHYSICALDRIVE_ID_RE.search(raw_id)
        if not match:
            continue
        device_id = match.group(1) or raw_id.strip()
        if not device_id:
            continue
        result[device_id] = {name: _to_int(item.get(name)) for name in _COUNTER_PROPS}
    return result


def get_reliability_counters() -> dict[str, dict]:
    """读取所有磁盘的可靠性计数器（温度 / 磨损 / 错误 / 通电时间等）。

    v1.2（#12）：主通道（Get-StorageReliabilityCounter）无数据时，改用
    MSFT_PhysicalDisk 的 CIM 通道兜底，避免「列出了盘却没有温度/通电时间」。

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
    result: dict[str, dict] = {}
    if data is not None:
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            device_id = str(item.get("DeviceId") if item.get("DeviceId") is not None else "")
            if device_id == "":
                continue
            result[device_id] = {name: _to_int(item.get(name)) for name in _COUNTER_PROPS}
    if not result:
        # v1.2（#12）：计数器主通道为空时走 CIM 兜底
        result = _counters_via_cim()
    return result
