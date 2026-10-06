# -*- coding: utf-8 -*-
"""离屏验证：导出报告里的盘面地图（把真实扫描记录喂进 store 再生成报告）。

会输出一份 demo 报告 HTML，方便直接用浏览器看效果。
用法：python test/_offscreen_report_check.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

from core import report as report_mod  # noqa: E402
from core import surface_scan as ss  # noqa: E402
from core import store as store_module  # noqa: E402


def _demo_cells() -> str:
    """造一份「盘尾有一段坏区 + 几处偏慢」的盘面地图。"""
    cells = [ss.CELL_OK] * 400
    for i in range(352, 360):
        cells[i] = ss.CELL_SLOW
    cells[372] = ss.CELL_VERY_SLOW
    for i in range(386, 394):
        cells[i] = ss.CELL_FAILED
    cells[395] = ss.CELL_FAILED_RUN
    return ss.encode_cells(cells)


def _demo_results() -> list[dict]:
    return [
        {
            "disk": {
                "device_id": "0",
                "model": "Kingston SV300S37A240G",
                "bus_type": "SATA",
                "media_type": "SSD",
                "size": 240 * 1024 ** 3,
                "serial": "DEMO0001",
                "health_status": "Healthy",
            },
            "verdict": {
                "level": "warning",
                "level_text": "警告",
                "score": 72,
                "monitor_supported": True,
                "reasons": ["重映射扇区曾经增长过 2 次"],
                "suggestions": ["建议先备份重要数据"],
            },
            "counters": {"Temperature": 41},
            "smart_attrs": [],
        }
    ]


def main() -> int:
    # Store 的参数是**数据目录**（内部会写 watu_disk_sprite.json），
    # 所以必须给一个临时目录，不能把 demo 数据落到 test/ 里污染仓库。
    tmp_dir = tempfile.mkdtemp(prefix="diskguard_demo_")
    prev = store_module._store
    store_module._store = store_module.Store(tmp_dir)
    try:
        store_module._store.save_surface_scan("0", {
            "model": "Kingston SV300S37A240G",
            "mode": "quick",
            "chunks_ok": 392,
            "chunks_failed": 8,
            "bytes_scanned": 1600 * 1024 ** 2,
            "elapsed_sec": 1.31,
            "speed_mb_s": 1955.4,
            "cells_code": _demo_cells(),
            "cells_scanned": 400,
            "slow_cells": 9,
            "very_slow_cells": 1,
            "bad_cells": 9,
            "baseline_ms": 2.1,
        })
        html = report_mod.build_report_html(_demo_results(), version="v1.2.0")
    finally:
        store_module._store = prev
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 输出到系统临时目录，不在项目里堆预览产物
    out = os.path.join(tempfile.gettempdir(), "_diskguard_report_preview.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"报告已生成（可直接用浏览器打开）：{out}")
    print(f"格子数：{html.count('<i style=')}")
    print(f"含盘面扫描卡片：{'盘面扫描（最近一次）' in html}")
    print(f"含偏慢统计：{'读取偏慢区域' in html}")
    assert html.count("<i style=") == 400, "报告里的盘面地图格子数不对"
    assert "盘面扫描（最近一次）" in html
    assert "读取偏慢区域" in html
    assert "#C93A3A" in html and "#D99A0B" in html and "#DD6B1D" in html
    return 0


if __name__ == "__main__":
    sys.exit(main())
