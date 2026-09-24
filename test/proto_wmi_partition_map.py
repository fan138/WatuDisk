# -*- coding: utf-8 -*-
"""验证：WMI 关联查询做盘符→物理磁盘映射（Get-Partition 失效时的备用通道）。"""
import json
import sys

sys.path.insert(0, r"D:\Projects\DiskGuard\src")
from core.powershell_runner import run_ps_json

QUERY = (
    "$rows = @(); "
    "$disks = Get-CimInstance Win32_DiskDrive; "
    "foreach ($dd in $disks) { "
    "$did = $dd.DeviceID -replace '\\\\', '\\\\\\\\'; "
    "$parts = Get-CimInstance -Query (\"ASSOCIATORS OF {Win32_DiskDrive.DeviceID='\" + $did + \"'} WHERE AssocClass=Win32_DiskDriveToDiskPartition\"); "
    "foreach ($p in $parts) { "
    "$letters = Get-CimInstance -Query (\"ASSOCIATORS OF {Win32_DiskPartition.DeviceID='\" + $p.DeviceID + \"'} WHERE AssocClass=Win32_LogicalDiskToPartition\"); "
    "foreach ($l in $letters) { "
    "$rows += [pscustomobject]@{drive = $l.DeviceID.TrimEnd(':'); disk = $dd.Index} "
    "} } }; "
    "$rows | ConvertTo-Json -Depth 2"
)

if __name__ == "__main__":
    result = run_ps_json(QUERY, timeout=30)
    print(json.dumps(result, ensure_ascii=False))
