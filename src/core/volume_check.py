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

import json
import re
from datetime import date

from core.powershell_runner import run_exe_text, run_ps_json, run_ps_text
from core.store import get_store

# 关联端点文本兼容两种格式（Windows 版本差异）：
#   Win32_DiskPartition.DeviceID="Disk #1, Partition #2"          （CIM 路径风格）
#   Win32_DiskPartition (DeviceID = "Disk #1, Partition #2")       （CimInstance.ToString() 风格）
_PARTITION_RE = re.compile(r'Win32_DiskPartition[^"]*?DeviceID\s*=\s*"([^"]+)"')
_DRIVE_RE = re.compile(r'Win32_LogicalDisk[^"]*?DeviceID\s*=\s*"([A-Za-z]):"')
_PHYSICALDRIVE_RE = re.compile(r"PHYSICALDRIVE(\d+)", re.IGNORECASE)

# v1.2.2 性能优化 B：Get-Partition 在本机稳定返回空（管理员下也空），
# 记录「standard 通道今日已确认不可用」，当天直接走 WMI 兜底，省去每次
# 约 7.5 秒的必然失败；次日自动重置重新尝试（环境修复后能自愈）。
_PARTMAP_STD_FAILED_KEY = "partmap_std_failed_date"

# v1.2.2 性能优化 C：合并查询的分段分隔符（三段 JSON 输出用；
# 取极不可能出现在盘符 / 设备路径里的字符串，避免误切）
_MERGE_SEP = "@@DG-VOL-SEP@@"


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


def _join_partition_rows(logical_rows: list[dict], disk_rows: list[dict]) -> dict[str, list[int]]:
    """把两张平铺关联表 join 成 {盘符: [物理盘号]}（v1.2.2 性能：合并通道共用）。

    逻辑与原 _get_partition_map_wmi 的 Python 侧 join 完全一致，抽出供
    单独 WMI 通道与合并查询两条路径复用，避免复制出第二份可能漂移的实现。
    """
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


def _parse_volume_items(items: list[dict]) -> dict[str, dict]:
    """解析 Get-Volume 输出为 {盘符: 空间信息}（v1.2.2 性能：合并通道共用）。

    字段与容错逻辑与原 _get_volume_space 完全一致。
    """
    result: dict[str, dict] = {}
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
            "fstype": str(item.get("FileSystemType") or "").strip(),
        }
    return result


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
    return _join_partition_rows(logical_rows, disk_rows)


def _get_partition_map() -> list[dict]:
    """获取有盘符的卷与其关联的物理磁盘编号（Get-Partition 优先，WMI 兜底）。

    v1.2.2 性能优化 B：Get-Partition 在部分系统（实测本机，管理员下也如此）
    稳定返回空，每次都先尝试再失败要白付约 7.5 秒。此时把「今日已确认
    standard 不可用」记入设置项，当天后续检测直接走 WMI 兜底；次日自动
    重置重新尝试——环境修复（如系统更新）后能自愈，不会把暂时的系统
    状态当成永久结论。

    Returns:
        [{drive: 'C', disk_numbers: [0], disk_number: 0}, ...]（按盘符去重，
        同一盘符多个分区合并为一条）；整体失败返回空列表。
    """
    store = get_store()
    today = date.today().isoformat()
    grouped: dict[str, list[int]] = {}
    if store.get_setting(_PARTMAP_STD_FAILED_KEY) != today:
        grouped = _get_partition_map_standard()
        if not grouped:
            # 今日首日失败：记录结论，当天不再重复必然失败的尝试
            store.set_setting(_PARTMAP_STD_FAILED_KEY, today)
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


def _safe_json_loads(text: str) -> object:
    """容错解析 JSON 段：失败返回 None（合并查询的分段解析用）。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _get_partition_and_space_merged() -> tuple[dict[str, list[int]], dict[str, dict]]:
    """WMI 分区关联 + 卷空间合并为一次 PowerShell 调用（v1.2.2 性能优化 C）。

    原实现落到 WMI 通道时：分区关联 2 次查询 + Get-Volume 1 次 = 3 次独立
    冷启动（本机实测约 13.4 秒）。合并为一条命令、分隔符分段输出，只付
    一次冷启动（本机实测约 8 秒）；解析逻辑复用 _join_partition_rows 与
    _parse_volume_items，与单独通道逐字节一致。

    Returns:
        ({盘符: [物理盘号]}, {盘符: 空间信息})；整体失败返回两个空 dict，
        由调用方按原兜底逻辑处理。
    """
    command = (
        f"$s = '{_MERGE_SEP}'; "
        "$p = Get-CimInstance Win32_LogicalDiskToPartition | ForEach-Object { "
        "[pscustomobject]@{ antecedent = $_.Antecedent.ToString(); "
        "dependent = $_.Dependent.ToString() } }; "
        "$d = Get-CimInstance Win32_DiskDriveToDiskPartition | ForEach-Object { "
        "[pscustomobject]@{ antecedent = $_.Antecedent.ToString(); "
        "dependent = $_.Dependent.ToString() } }; "
        "$v = Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter } | "
        "Select-Object DriveLetter, Size, SizeRemaining, FileSystemType; "
        "($p | ConvertTo-Json -Depth 2) + $s + ($d | ConvertTo-Json -Depth 2) + $s + "
        "($v | ConvertTo-Json -Depth 2)"
    )
    text = run_ps_text(command, timeout=45)
    if text is None:
        return {}, {}
    parts = text.strip().split(_MERGE_SEP)
    if len(parts) != 3:
        return {}, {}
    logical_rows = _iter_ps_items(_safe_json_loads(parts[0]))
    disk_rows = _iter_ps_items(_safe_json_loads(parts[1]))
    volume_items = _iter_ps_items(_safe_json_loads(parts[2]))
    if not logical_rows or not disk_rows:
        return {}, {}
    return _join_partition_rows(logical_rows, disk_rows), _parse_volume_items(volume_items)


def _collect_volume_maps() -> tuple[dict[str, list[int]], dict[str, dict]]:
    """按可用通道拿 (盘符→物理盘分组, 卷空间)（v1.2.2 性能：check_volumes 入口）。

    - standard 通道可用：与原逻辑相同，分区图与卷空间各查各的；
    - 落到 WMI 通道：分区关联与卷空间合并为一次调用（_get_partition_and_space_merged），
      把 3 次冷启动降为 1 次。
    """
    store = get_store()
    today = date.today().isoformat()
    if store.get_setting(_PARTMAP_STD_FAILED_KEY) != today:
        grouped = _get_partition_map_standard()
        if not grouped:
            store.set_setting(_PARTMAP_STD_FAILED_KEY, today)
        if grouped:
            return grouped, _get_volume_space()
    return _get_partition_and_space_merged()


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

    v1.2.2（#10）：fsutil 改为直调（run_exe_text），不再套 PowerShell 进程——
    实测每次省约 2 秒冷启动，脏位查询从「每卷 2.2 秒」降到几乎无感。

    Returns:
        True=已置位 / False=未置位 / None=无法读取（权限不足等）。
    """
    text = run_exe_text(["fsutil", "dirty", "query", f"{drive_letter}:"], timeout=15, check_code=False)
    if text is None or not text.strip():
        return None
    return _parse_dirty_output(text)


def _get_volume_space() -> dict[str, dict]:
    """获取各卷容量、剩余空间与文件系统类型（Get-Volume，只读、快）。

    v1.2（#13）：增返回 fstype，供判读层区分 exFAT/FAT 等跨平台盘——
    这类盘的脏位多为未安全弹出或被 PS5 等设备使用所致，属常见现象。

    Returns:
        {'C': {'size': int, 'free': int, 'free_pct': float, 'fstype': str}, ...}；
        失败返回空。
    """
    command = (
        "Get-Volume -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DriveLetter } | "
        "Select-Object DriveLetter, Size, SizeRemaining, FileSystemType | ConvertTo-Json -Depth 2"
    )
    data = run_ps_json(command, timeout=20)
    return _parse_volume_items(_iter_ps_items(data))


def check_volumes() -> list[dict]:
    """检查所有本地卷的损坏位标志 + 剩余空间 + 文件系统类型（同一卷只查一次 dirty）。

    v1.2（#13）：每项增 fstype 字段（来自 Get-Volume 的 FileSystemType），
    供 verdict 区分 exFAT/FAT 跨平台盘的常见脏位场景。
    v1.2.2（性能）：分区图与卷空间改由 _collect_volume_maps 统一获取——
    落到 WMI 通道时合并为一次 PowerShell 调用（原 3 次冷启动）。

    Returns:
        [{drive: 'C:', dirty: bool|None, disk_number: int|None,
          disk_numbers: [int, ...], size: int|None, free: int|None,
          free_pct: float|None, fstype: str}, ...]；
        跨盘卷的 disk_numbers 可含多个磁盘；整体失败返回空列表。
    """
    grouped, space_map = _collect_volume_maps()
    results: list[dict] = []
    for letter in sorted(grouped):
        numbers = sorted(set(grouped[letter]))
        dirty = _query_dirty(letter)
        space = space_map.get(letter) or {}
        results.append(
            {
                "drive": f"{letter}:",
                "dirty": dirty,
                "disk_number": numbers[0] if numbers else None,
                "disk_numbers": numbers,
                "size": space.get("size"),
                "free": space.get("free"),
                "free_pct": space.get("free_pct"),
                "fstype": space.get("fstype", ""),
            }
        )
    return results
