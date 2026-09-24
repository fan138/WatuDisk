# -*- coding: utf-8 -*-
"""系统事件日志扫描：最近 30 天与磁盘相关的错误 / 警告。

数据来源：Get-WinEvent 查询 System 日志，Provider 限定为
disk / Ntfs / volmgr / storahci / stornvme / volsnap 等。
解析失败返回空列表，不影响其他检测项。
"""
from __future__ import annotations

import re

from core.powershell_runner import run_ps_json

PROVIDERS = ("disk", "Disk", "Ntfs", "volmgr", "storahci", "stornvme", "volsnap", "vhdmp", "partmgr")

LEVEL_TEXT = {1: "严重", 2: "错误", 3: "警告"}

_MAX_MESSAGE_LEN = 300


def _events_to_json_expr() -> str:
    """生成把事件列表转换为 JSON 的 PowerShell 表达式片段。"""
    return (
        "@($ev) | Where-Object { $_.Level -le 3 } | ForEach-Object { "
        "[PSCustomObject]@{ Time = $_.TimeCreated.ToString('yyyy-MM-dd HH:mm'); "
        "Provider = $_.ProviderName; Level = $_.Level; Message = $_.Message } } "
        "| ConvertTo-Json -Depth 3"
    )


def scan_disk_events(days: int = 30, max_events: int = 300) -> list[dict]:
    """扫描最近 N 天内磁盘相关的错误 / 警告事件。

    Args:
        days: 回溯天数。
        max_events: 最多返回的事件条数。

    Returns:
        事件列表（time / provider / level / level_text / message），
        按时间倒序；解析失败返回空列表。
    """
    providers = "','".join(PROVIDERS)
    primary = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$ev = Get-WinEvent -FilterHashtable @{ LogName = 'System'; "
        f"StartTime = (Get-Date).AddDays(-{days}); ProviderName = '{providers}' }} "
        f"-MaxEvents {max_events}; "
        "if ($ev) { " + _events_to_json_expr() + " } else { Write-Output '[]' }"
    )
    data = run_ps_json(primary, timeout=60)

    if data is None:
        # 主查询失败（可能系统缺少部分 Provider），退化为全量查询后本地过滤
        provider_list = "@('" + "','".join(PROVIDERS) + "')"
        fallback = (
            "$ErrorActionPreference = 'SilentlyContinue'; "
            "$ev = Get-WinEvent -FilterHashtable @{ LogName = 'System'; "
            f"StartTime = (Get-Date).AddDays(-{days}) }} -MaxEvents 3000; "
            "if ($ev) { $ev = $ev | Where-Object { $_.Level -le 3 -and "
            f"$_.ProviderName -in {provider_list} }}; "
            "if ($ev) { $ev = @($ev) | Select-Object -First " + str(max_events) + "; "
            + _events_to_json_expr() + " } else { Write-Output '[]' }"
        )
        data = run_ps_json(fallback, timeout=90)
        if data is None:
            return []

    items = data if isinstance(data, list) else [data]
    events: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            level = int(item.get("Level") or 2)
        except (TypeError, ValueError):
            level = 2
        message = str(item.get("Message") or "").strip()
        message = message.replace("\r", " ").replace("\n", " ")[:_MAX_MESSAGE_LEN]
        events.append(
            {
                "time": str(item.get("Time") or ""),
                "provider": str(item.get("Provider") or ""),
                "level": level,
                "level_text": LEVEL_TEXT.get(level, "错误"),
                "message": message,
            }
        )
    return events


def match_events_to_disk(events: list[dict], disk: dict) -> tuple[int, list[dict]]:
    """把事件列表匹配到指定磁盘。

    匹配依据（命中任意一条即算相关）：
    - 消息中包含 \\Device\\HarddiskN（N 为该盘的 DeviceId，且不吞并编号）；
    - 消息中包含磁盘型号（去除空白后模糊包含，长度 >= 6 才参与匹配）；
    - 消息中包含序列号。

    Returns:
        (相关事件总数, 最近最多 5 条事件列表)。
    """
    device_id = str(disk.get("device_id") or "")
    model = str(disk.get("model") or "").strip()
    serial = str(disk.get("serial") or "").strip()

    patterns: list[re.Pattern] = []
    if device_id != "":
        # Harddisk0 不应匹配 Harddisk01：用负向前瞻排除后续数字
        patterns.append(re.compile(r"harddisk" + re.escape(device_id) + r"(?!\d)", re.IGNORECASE))
    model_key = re.sub(r"\s+", "", model).lower()

    matched: list[dict] = []
    recent: list[dict] = []
    for event in events:
        message = str(event.get("message") or "").lower()
        flat = re.sub(r"\s+", "", message)
        hit = any(p.search(message) for p in patterns)
        if not hit and len(model_key) >= 6 and model_key in flat:
            hit = True
        if not hit and serial and serial.lower() in message:
            hit = True
        if hit:
            matched.append(event)
            if len(recent) < 5:
                recent.append(event)
    return len(matched), recent
