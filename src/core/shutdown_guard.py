# -*- coding: utf-8 -*-
"""关机 / 重启守护（v1.3）。

设计原则（用户要求：避免对硬盘造成伤害、不拖慢关机）：
- 关机瞬间只做一件事：直读 NVMe 健康日志（毫秒级纯读取，不写盘、
  不做任何扫描类操作，对硬盘零伤害）；
- 总耗时上限 2 秒（Windows 给应用的宽限约 5 秒），超时立即放弃；
- 永远不拦截 / 拖延用户的关机——发现问题只做两件事：
  1) 尽力弹一次气泡提示（关机过程中系统可能不显示，属尽力而为）；
  2) 把「待警示」标记写入本地数据文件，下次开机郑重提醒。
- SATA 盘的 WMI 查询太慢，关机场景跳过（开机静默体检会覆盖）。
"""
from __future__ import annotations

import time

from core import nvme_health

QUICK_CHECK_TIMEOUT_S = 2.0


def quick_check(device_ids: list[str], deadline_ts: float | None = None) -> list[dict]:
    """关机前的快速健康复查（只读 NVMe 健康日志）。

    Args:
        device_ids: 最近一次检测的硬盘 device_id 列表（如 ["0", "1"]）。
        deadline_ts: 绝对时间戳上限；None 则用默认 2 秒预算。

    Returns:
        异常盘列表 [{device_id, reasons: [...]}]；全部正常返回 []。
    """
    deadline = deadline_ts if deadline_ts is not None else time.time() + QUICK_CHECK_TIMEOUT_S
    problems: list[dict] = []
    for device_id in device_ids or []:
        if time.time() > deadline:
            break  # 超时立即放弃，绝不拖慢关机
        try:
            health = nvme_health.query_nvme_health(int(str(device_id)))
        except (TypeError, ValueError):
            continue
        if health is None:
            continue
        reasons: list[str] = []
        if health.get("critical_warning"):
            reasons.append("硬盘自报危险警告信号")
        spare = health.get("available_spare_pct")
        threshold = health.get("spare_threshold")
        if isinstance(spare, int) and isinstance(threshold, int) and spare < threshold:
            reasons.append(f"备用空间仅 {spare}%（低于阈值 {threshold}%）")
        if health.get("media_errors"):
            reasons.append(f"发现 {health['media_errors']} 个媒体错误")
        if health.get("percentage_used") is not None and health["percentage_used"] >= 90:
            reasons.append(f"寿命已消耗 {health['percentage_used']}%")
        if reasons:
            problems.append({"device_id": str(device_id), "reasons": reasons})
    return problems
