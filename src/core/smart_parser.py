# -*- coding: utf-8 -*-
"""SATA SMART 原始属性解析。

数据来源：root\\wmi 命名空间的 MSStorageDriver_FailurePredictData 类，
VendorSpecific 字段以 2 字节版本号开头，随后是若干 12 字节属性结构：
[0] 属性ID  [1-2] 标志  [3] 当前值  [4] 最差值  [5-10] 原始值(小端)  [11] 保留。

NVMe 盘（BusType=NVMe）没有此结构，由调用方改用 StorageReliabilityCounter。
解析失败一律优雅降级：返回空列表 / 空字典，绝不抛出异常导致崩溃。
"""
from __future__ import annotations

import re

from core.powershell_runner import run_ps_json

# 常见 SMART 属性的中文对照表
ATTR_NAMES: dict[int, str] = {
    0x01: "读取错误率",
    0x05: "重映射扇区数",
    0x07: "寻道错误率",
    0x09: "通电时间",
    0x0C: "通电次数",
    0xAA: "可用备用块数",
    0xAD: "SSD 磨损指示",
    0xB1: "磨损范围计数",
    0xB4: "SSD 磨损计数",
    0xB7: "SATA 下行错误",
    0xB8: "端到端错误",
    0xC2: "温度",
    0xC5: "待映射扇区数",
    0xC6: "无法修正扇区数",
    0xC7: "接口传输错误（CRC）",
    0xC8: "写入错误率",
    0xCA: "SSD 剩余寿命",
    0xE7: "SSD 剩余寿命",
    0xE9: "SSD 磨损平衡",
    0xF1: "累计写入量",
    0xF2: "累计读取量",
}

# 评分重点关注属性
KEY_ATTR_IDS = (0x05, 0xC5, 0xC6, 0xC7)

_CIM_COMMAND = (
    "Get-CimInstance -Namespace root/wmi -ClassName MSStorageDriver_FailurePredictData "
    "-ErrorAction SilentlyContinue | ForEach-Object { "
    "[PSCustomObject]@{ InstanceName = $_.InstanceName; "
    "VendorSpecific = ($_.VendorSpecific -join ',') } } | ConvertTo-Json -Depth 3"
)


def attr_display_name(attr_id: int) -> str:
    """返回属性中文名，未知属性返回十六进制占位名。"""
    return ATTR_NAMES.get(attr_id, f"未知属性 0x{attr_id:02X}")


def parse_vendor_attributes(vendor_bytes: object) -> list[dict]:
    """解析 VendorSpecific 字节数组为 SMART 属性列表。

    Args:
        vendor_bytes: 可迭代的字节数据（0-255）。

    Returns:
        属性列表，每项含 id / hex / name / value / raw；数据无效返回空列表。
    """
    try:
        data = [int(b) & 0xFF for b in vendor_bytes]
    except (TypeError, ValueError):
        return []
    # 至少需要 2 字节版本号 + 1 个完整属性结构
    if len(data) < 14:
        return []
    attrs: list[dict] = []
    offset = 2  # 跳过 2 字节版本号
    while offset + 12 <= len(data):
        block = data[offset:offset + 12]
        attr_id = block[0]
        if attr_id == 0:  # 属性表以 0 结尾
            break
        raw_int = int.from_bytes(block[5:11], "little")
        attrs.append(
            {
                "id": attr_id,
                "hex": f"0x{attr_id:02X}",
                "name": attr_display_name(attr_id),
                "value": block[3],
                "raw": raw_int,
            }
        )
        offset += 12
    return attrs


def fetch_raw_records() -> list[dict]:
    """从 WMI 抓取全部 SMART 原始记录。

    Returns:
        记录列表，每项含 instance（实例名）与 attrs（已解析属性列表）；
        失败返回空列表。
    """
    data = run_ps_json(_CIM_COMMAND, timeout=45)
    if data is None:
        return []
    items = data if isinstance(data, list) else [data]
    records: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        vendor_raw = item.get("VendorSpecific")
        if vendor_raw is None:
            continue
        try:
            byte_list = [int(x) for x in str(vendor_raw).split(",") if x.strip() != ""]
        except ValueError:
            continue
        records.append(
            {
                "instance": str(item.get("InstanceName") or ""),
                "attrs": parse_vendor_attributes(byte_list),
            }
        )
    return records


def _norm(text: str) -> str:
    """归一化字符串用于模糊匹配（去空白、转大写）。"""
    return re.sub(r"\s+", "", text).upper()


def get_smart_for_disks(disks: list[dict]) -> dict[str, list[dict]]:
    """为每块 SATA 物理盘匹配并解析 SMART 属性。

    NVMe / USB 盘跳过（NVMe 由 StorageReliabilityCounter 提供数据）。
    匹配策略：先按型号 / 序列号与 WMI 实例名匹配；无法匹配的记录按顺序
    兜底分配给尚未取得属性的 SATA 盘。

    Returns:
        device_id -> 属性列表；失败返回空字典。
    """
    targets = [
        d
        for d in disks
        if str(d.get("bus_type", "")).upper() not in ("NVME", "USB")
    ]
    if not targets:
        return {}
    records = fetch_raw_records()
    if not records:
        return {}

    result: dict[str, list[dict]] = {}
    used: set[int] = set()

    # 第一轮：按型号 / 序列号精确-ish 匹配
    for disk in targets:
        model_key = _norm(str(disk.get("model") or ""))
        serial = str(disk.get("serial") or "").strip().upper()
        for index, record in enumerate(records):
            if index in used:
                continue
            instance = _norm(record.get("instance") or "")
            if (model_key and model_key in instance) or (serial and serial in instance):
                result[str(disk["device_id"])] = record["attrs"]
                used.add(index)
                break

    # 第二轮：剩余记录按顺序分给仍未匹配的盘（常见于单盘机器）
    leftover = [i for i in range(len(records)) if i not in used]
    for disk in targets:
        device_id = str(disk["device_id"])
        if device_id in result or not leftover:
            continue
        index = leftover.pop(0)
        result[device_id] = records[index]["attrs"]
        used.add(index)

    return result
