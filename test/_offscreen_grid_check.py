# -*- coding: utf-8 -*-
"""验证：盘面扫描对话框的 20×20 格子热力图能否正常渲染并逐格点亮。

两种用法：
- 结构/逻辑验证（不弹窗、可进 CI）：
      QT_QPA_PLATFORM=offscreen python test/_offscreen_grid_check.py
- 抓一张真实渲染截图（会短暂弹出窗口，中文才显示得出来）：
      python test/_offscreen_grid_check.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "src")))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import surface_scan as ss  # noqa: E402
from ui.surface_scan_dialog import SurfaceScanDialog, SurfaceGrid  # noqa: E402

SHOT = os.path.join(HERE, "_grid_preview.png")


def _seed_demo_cells(grid: SurfaceGrid) -> None:
    """造一份演示数据：前段正常、中段偏慢、末尾一段坏区。"""
    for i in range(300):
        grid.set_state(i, ss.CELL_OK)
    for i in range(300, 320):
        grid.set_state(i, ss.CELL_SLOW)
    for i in range(320, 330):
        grid.set_state(i, ss.CELL_VERY_SLOW)
    for i in range(340, 372):
        grid.set_state(i, ss.CELL_FAILED)
    for i in range(372, 380):
        grid.set_state(i, ss.CELL_FAILED_RUN)


def main() -> int:
    app = QApplication(sys.argv)

    disks = [
        {"device_id": "0", "model": "NVMe 演示盘", "size": 1024 ** 4},
        {"device_id": "1", "model": "机械演示盘", "size": 2 * 1024 ** 4},
    ]
    dlg = SurfaceScanDialog(disks)
    dlg.show()

    grid = dlg._grid
    assert isinstance(grid, SurfaceGrid), "对话框里没有格子控件"
    assert len(grid.states()) == ss.GRID_CELLS, f"格子数不对：{len(grid.states())}"
    assert grid.scanned_count() == 0, "初始应全是未扫描的灰色"

    _seed_demo_cells(grid)
    dlg._update_grid_info()

    print(f"窗口标题: {dlg.windowTitle()}")
    print(f"已扫格数: {dlg._grid_count.text()}")
    print("图例: " + " | ".join(label.text() for label in dlg._legend_labels.values()))
    print(f"抽查密度: {dlg._density.text()}")

    assert f"{grid.scanned_count()} / 400 格" in dlg._grid_count.text(), \
        f"已扫格数未更新：{dlg._grid_count.text()}"
    assert any("300" in label.text() for label in dlg._legend_labels.values()), "图例未更新数字"

    # 报告里的迷你格子图（同一份数据、同一套颜色）
    from core import report as report_mod

    html = report_mod._grid_map_html(ss.encode_cells(grid.states()))
    print(f"报告格子数: {html.count('<i style=')}")
    assert html.count("<i style=") == ss.GRID_CELLS, "报告格子数不对"

    def _grab_and_quit() -> None:
        dlg.grab().save(SHOT)
        print(f"截图已存: {SHOT}")
        print("OK：格子热力图渲染正常")
        app.quit()

    # 给窗口一点时间完成首次绘制，再抓图（离屏平台抓图没有字体，仅逻辑可用）
    QTimer.singleShot(700, _grab_and_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
