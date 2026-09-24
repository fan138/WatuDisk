# -*- coding: utf-8 -*-
"""卷损坏位（Dirty Bit）检查。

通过 fsutil dirty query 逐卷查询「损坏位」标志（需要管理员权限），
并把盘符映射到物理磁盘编号，便于归因到具体硬盘。

盘符 -> 物理盘映射（v1.2 增强）：
- 优先 Get-Partition（常规环境）；
- Storage Spaces 等环境下 Get-Partition 返回空列表，此时降级用 WMI
  平铺查询（Win32_LogicalDiskToPartition + Win32_DiskDriveToDiskPartition）
  在 Python 侧做字符串解析关联（禁用嵌套 WQL 关联查询——实测报 0x80041002）；
- 跨盘卷（如跨两块 NVMe 的 Storage Spaces 卷）同一盘符可能对应多个磁盘，
  数据结构允许 disk_numbers 多值；dirty 结果关联到每个关联磁盘。

fsutil 退出码语义不标准（某些版本脏卷返回 1），因此关闭退出码检查、
直接解析输出文本。任何失败优雅降级，不抛异常。
"""
from __future__ import annotations

import re

from core.powershell_runner import run_ps_json, run_ps_text

# 关联端点文本兼容两种格式（Windows 版本差异）：
#   Win32_DiskPartition.DeviceID="Disk #1, Partition #2"          （CIM 路径风格）
#   Win32_DiskPartition (DeviceID = "Disk #1, Partition #2")       （CimInstance.ToString() 风格）
_PARTITION_RE = re.compile(r'Win32_DiskPartition[^"]*?DeviceID\s*=\s*"([^"]+)"')
_DRIVE_RE = re.compile(r'Win32_LogicalDisk[^"]*?DeviceID\s*=\s*"([A-Za-z]):"')
_PHYSICALDRIVE_RE = re.compile(r"PHYSICALDRIVE(\d+)", re.IGNORECASE)


def _iter_ps_items(data: object) -> list[dict]:
    """把 ConvertTo-Json 输出统一为 dict 列表（单对象 / 列表 / 非法输入）。"""
    if data is None:
        return []
    items = data if isinstance(data, list) else [data]
    return [item for item in items if isinstance(item, dict)]


def _get_partition_map_standard() -> dict[str, list[int]]:
    """通道一：Get-Partition 获取盘符与所属物理磁盘编号。

    Returns:
        {drive_letter: [disk_number, ...], ...}；失败或环境不支持返回空 dict。
    """
    command = (
        "Get-Partition -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DriveLetter } | "
        "Select-Object DriveLetter, DiskNumber | ConvertTo-Json -Depth 2"
    )
    data = run_ps_json(command, timeout=30)
    grouped: dict[str, list[int]] = {}
    for item in _iter_ps_items(data):
        letter = str(item.get("DriveLetter") or "").strip().rstrip(":").upper()
        if not letter:
            continue
        number = item.get("DiskNumber")
        try:
            number = int(number) if number is not None else None
        except (TypeError, ValueError):
            number = None
        if number is not None:
            grouped.setdefault(letter, []).append(number)
    return grouped


def _get_partition_map_wmi() -> dict[str, list[int]]:
    r"""通道二（备用）：WMI 平铺查询 + Python 侧关联。

    两个平铺查询（真机已验证均可返回数据）：
    - Win32_LogicalDiskToPartition：Antecedent（分区）-> Dependent（盘符）；
    - Win32_DiskDriveToDiskPartition：Antecedent（\\\.\\PHYSICALDRIVE{n}）-> Dependent（分区）。

    注意：Antecedent / Dependent 是内嵌 CimInstance 对象，直接 ConvertTo-Json
    会展开成巨型嵌套结构；必须先 ToString() 投影成「类名 (DeviceID = "值")」
    文本再序列化，Python 侧用正则解析。

    Returns:
        {drive_letter: [disk_number, ...], ...}；任一查询失败返回空 dict。
    """
    logical_query = (
        "Get-CimInstance Win32_LogicalDiskToPartition | ForEach-Object { "
        "[pscustomobject]@{ antecedent = $_.Antecedent.ToString(); "
        "dependent = $_.Dependent.ToString() } } | ConvertTo-Json -Depth 3"
    )
    disk_query = (
        "Get-CimInstance Win32_DiskDriveToDiskPartition | ForEach-Object { "
        "[pscustomobject]@{ antecedent = $_.Antecedent.ToString(); "
        "dependent = $_.Dependent.ToString() } } | ConvertTo-Json -Depth 3"
    )
    logical_rows = _iter_ps_items(run_ps_json(logical_query, timeout=30))
    disk_rows = _iter_ps_items(run_ps_json(disk_query, timeout=30))
    if not logical_rows or not disk_rows:
        return {}

    # 第一张表：分区 DeviceID -> 盘符集合（键名与 ToString 投影一致，小写）
    partition_to_drives: dict[str, set[str]] = {}
    for row in logical_rows:
        antecedent = row.get("antecedent") or row.get("Antecedent") or ""
        dependent = row.get("dependent") or row.get("Dependent") or ""
        partition_match = _PARTITION_RE.search(str(antecedent))
        drive_match = _DRIVE_RE.search(str(dependent))
        if partition_match and drive_match:
            partition_to_drives.setdefault(partition_match.group(1), set()).add(
                drive_match.group(1).upper()
            )

    # 第二张表：分区 DeviceID -> 物理盘编号，两表在 Python 侧 join
    drive_to_disks: dict[str, set[int]] = {}
    for row in disk_rows:
        antecedent = row.get("antecedent") or row.get("Antecedent") or ""
        dependent = row.get("dependent") or row.get("Dependent") or ""
        partition_match = _PARTITION_RE.search(str(dependent))
        disk_match = _PHYSICALDRIVE_RE.search(str(antecedent))
        if not (partition_match and disk_match):
            continue
        try:
            number = int(disk_match.group(1))
        except ValueError:
            continue
        for drive in partition_to_drives.get(partition_match.group(1), ()):
            drive_to_disks.setdefault(drive, set()).add(number)
    return {drive: sorted(numbers) for drive, numbers in drive_to_disks.items()}


def _get_partition_map() -> list[dict]:
    """获取有盘符的卷与其关联的物理磁盘编号（Get-Partition 优先，WMI 兜底）。

    Returns:
        [{drive: 'C', disk_numbers: [0], disk_number: 0}, ...]（按盘符去重，
        同一盘符多个分区合并为一条）；整体失败返回空列表。
    """
    grouped = _get_partition_map_standard()
    if not grouped:
        # Storage Spaces 等环境 Get-Partition 返回空 -> WMI 备用通道
        grouped = _get_partition_map_wmi()
    result: list[dict] = []
    for letter in sorted(grouped):
        numbers = sorted(set(grouped[letter]))
        result.append(
            {
                "drive": letter,
                "disk_numbers": numbers,
                "disk_number": numbers[0] if numbers else None,  # v1.1 兼容字段
            }
        )
    return result


def _parse_dirty_output(text: str) -> bool:
    """解析 fsutil dirty query 输出，判断损坏位是否置位。

    典型输出：
    - 英文：Volume - C: is NOT Dirty / Volume - C: is Dirty
    - 中文：卷 - C: 没有设置损坏位。 / 卷 - C: 已设置损坏位。
    """
    upper = text.upper()
    flat = text.replace(" ", "")
    # 先判断否定情形（避免 "is Dirty" 误匹配 "is NOT Dirty"）
    if "NOTDIRTY" in flat.upper() or "NOT" in upper:
        return False
    if any(keyword in text for keyword in ("没有", "不是", "未设置", "未损坏", "未置位")):
        return False
    if "DIRTY" in upper or "损坏位" in text or "已设置" in text or "置位" in text:
        return True
    return False


def _query_dirty(drive_letter: str) -> bool | None:
    """查询单个卷的损坏位状态。

    Returns:
        True=已置位 / False=未置位 / None=无法读取（权限不足等）。
    """
    command = f"fsutil dirty query {drive_letter}:"
    text = run_ps_text(command, timeout=15, check_code=False)
    if text is None or not text.strip():
        return None
    return _parse_dirty_output(text)


def _get_volume_space() -> dict[str, dict]:
    """获取各卷容量与剩余空间（Get-Volume，只读、快）。

    Returns:
        {'C': {'size': int, 'free': int, 'free_pct': float}, ...}；失败返回空。
    """
    command = (
        "Get-Volume -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DriveLetter } | "
        "Select-Object DriveLetter, Size, SizeRemaining | ConvertTo-Json -Depth 2"
    )
    data = run_ps_json(command, timeout=20)
    result: dict[str, dict] = {}
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for item in items:
        letter = str(item.get("DriveLetter") or "").strip().rstrip(":").upper()
        if not letter:
            continue
        try:
            size = float(item.get("Size") or 0)
            free = float(item.get("SizeRemaining") or 0)
        except (TypeError, ValueError):
            continue
        if size <= 0:
            continue
        result[letter] = {
            "size": int(size),
            "free": int(free),
            "free_pct": round(free / size * 100.0, 1),
        }
    return result


def check_volumes() -> list[dict]:
    """检查所有本地卷的损坏位标志 + 剩余空间（同一卷只查一次 dirty）。

    Returns:
        [{drive: 'C:', dirty: bool|None, disk_number: int|None,
          disk_numbers: [int, ...], size: int|None, free: int|None,
          free_pct: float|None}, ...]；
        跨盘卷的 disk_numbers 可含多个磁盘；整体失败返回空列表。
    """
    partitions = _get_partition_map()
    space_map = _get_volume_space()
    results: list[dict] = []
    for part in partitions:
        dirty = _query_dirty(part["drive"])
        numbers = list(part.get("disk_numbers") or [])
        letter = str(part["drive"]).rstrip(":").upper()
        space = space_map.get(letter) or {}
        results.append(
            {
                "drive": f"{part['drive']}:",
                "dirty": dirty,
                "disk_number": part.get("disk_number"),
                "disk_numbers": numbers,
                "size": space.get("size"),
                "free": space.get("free"),
                "free_pct": space.get("free_pct"),
            }
        )
    return results
