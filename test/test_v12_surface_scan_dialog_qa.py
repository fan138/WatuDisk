# -*- coding: utf-8 -*-
"""v1.2 盘面扫描对话框交互增强回归测试。

锁定本次新增的三件事：
1. 按钮合并：空闲「开始扫描/关闭」↔ 扫描中「停止/隐藏」，且隐藏后后台继续扫。
2. 多盘连扫：勾选多块盘 → 队列按勾选顺序；自动连扫开关控制 A→B→C。
3. 结果复用：报告里明确「取自最近一次扫描、无需为导出重扫」。

不触发真实磁盘读取：仅测状态机与队列，必要时用 mock 替掉发起扫描的入口。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.surface_scan_dialog import SurfaceScanDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

_FAKE_DISKS = [
    {"device_id": "0", "model": "NVMe 盘A", "size": 1024 ** 4},
    {"device_id": "1", "model": "机械盘B", "size": 2 * 1024 ** 4},
    {"device_id": "2", "model": "SSD 盘C", "size": 512 * 1024 ** 3},
]


def _dlg() -> SurfaceScanDialog:
    return SurfaceScanDialog(list(_FAKE_DISKS))


def test_initial_state():
    """空闲态：主按钮「开始扫描」、次按钮「关闭」、选盘可用。"""
    d = _dlg()
    assert d._go_btn.text() == "开始扫描", d._go_btn.text()
    assert d._sec_btn.text() == "关闭", d._sec_btn.text()
    assert d._scanning is False
    assert d._disk_list.isEnabled()


def test_enter_scanning_labels():
    """进入扫描中：主按钮「停止」、次按钮「隐藏」、选盘/档位/连扫开关锁定。"""
    d = _dlg()
    d._enter_scanning()
    assert d._scanning is True
    assert d._go_btn.text() == "停止", d._go_btn.text()
    assert d._sec_btn.text() == "隐藏", d._sec_btn.text()
    assert not d._disk_list.isEnabled()
    assert not d._mode_box.isEnabled()
    assert not d._chain_cb.isEnabled()


def test_enter_idle_labels():
    """回到空闲：主按钮恢复可发起扫描、次按钮「关闭」、选择恢复可用。"""
    d = _dlg()
    d._enter_scanning()
    d._enter_idle("重新扫描")
    assert d._scanning is False
    assert d._paused is False
    assert d._go_btn.text() == "重新扫描"
    assert d._sec_btn.text() == "关闭"
    assert d._disk_list.isEnabled()


def test_queue_order_and_filter():
    """队列按界面勾选顺序取设备编号；未勾选的不进队列。"""
    d = _dlg()
    d._disk_items[1].setCheckState(Qt.CheckState.Unchecked)  # 取消第 2 块
    q = d._build_queue_from_selection()
    assert q == ["0", "2"], q

    # 全勾选时顺序与界面一致
    for it in d._disk_items:
        it.setCheckState(Qt.CheckState.Checked)
    assert d._build_queue_from_selection() == ["0", "1", "2"]


def test_hidden_flag_during_scan():
    """扫描中点「隐藏」：置 _was_hidden 并真的收起窗口（后台继续）。"""
    d = _dlg()
    d._enter_scanning()
    d._was_hidden = False
    d._on_secondary()
    try:
        assert d._was_hidden is True
        assert d.isHidden() is True
    finally:
        d.showNormal()  # 还原，避免影响后续


def test_go_branch_stop_when_scanning():
    """主按钮在扫描中 = 停止。"""
    d = _dlg()
    d._scanning = True
    calls = []
    d._on_stop = lambda: calls.append("stop")
    d._start_next = lambda: calls.append("next")
    d._on_start = lambda: calls.append("start")
    d._on_go()
    assert calls == ["stop"], calls


def test_go_branch_start_when_idle():
    """主按钮在空闲 = 开始扫描。"""
    d = _dlg()
    d._scanning = False
    d._paused = False
    calls = []
    d._on_stop = lambda: calls.append("stop")
    d._start_next = lambda: calls.append("next")
    d._on_start = lambda: calls.append("start")
    d._on_go()
    assert calls == ["start"], calls


def test_go_branch_continue_when_paused():
    """主按钮在手动连扫停顿 = 继续下一台。"""
    d = _dlg()
    d._scanning = False
    d._paused = True
    calls = []
    d._on_stop = lambda: calls.append("stop")
    d._start_next = lambda: calls.append("next")
    d._on_start = lambda: calls.append("start")
    d._on_go()
    assert calls == ["next"], calls


def test_secondary_branch_close_when_idle():
    """空闲时次按钮 = 关闭（走 _finish，不是隐藏）。"""
    d = _dlg()
    d._scanning = False
    called = []
    d._finish = lambda: called.append("finish")
    d._hide_during_scan = lambda: called.append("hide")
    d._on_secondary()
    assert called == ["finish"], called


def test_secondary_branch_hide_when_scanning():
    """扫描中次按钮 = 隐藏（走 _hide_during_scan，不是关闭）。"""
    d = _dlg()
    d._scanning = True
    called = []
    d._finish = lambda: called.append("finish")
    d._hide_during_scan = lambda: called.append("hide")
    d._on_secondary()
    assert called == ["hide"], called


def test_close_event_hides_when_scanning():
    """扫描中按 X/Esc 应隐藏而不是关闭（保护后台扫描不被杀）。"""
    d = _dlg()
    d._enter_scanning()
    d._was_hidden = False
    d.close()  # 模拟用户点 X
    try:
        assert d.isHidden() is True, "扫描中关闭应改为隐藏"
        assert d._was_hidden is True
    finally:
        d.showNormal()


def test_report_reuse_note_present():
    """报告章节必须写明「最近一次 / 无需为刷新结果而重新扫描」。"""
    import core.store as store_mod
    from core import report as report_mod
    from unittest.mock import patch

    fake_record = {
        "model": "NVMe 盘A",
        "mode": "quick",
        "chunks_ok": 400,
        "chunks_failed": 0,
        "bytes_scanned": 1600 * 1024 * 1024,
        "elapsed_sec": 1.2,
        "speed_mb_s": 1300,
        "cells_code": "1" * 400,
        "cells_scanned": 400,
        "slow_cells": 0,
        "very_slow_cells": 0,
        "bad_cells": 0,
        "baseline_ms": 1.0,
    }
    with patch.object(store_mod, "get_store") as m:
        m.return_value.all_surface_scans.return_value = {"0": fake_record}
        results = [{"disk": {"device_id": "0", "model": "NVMe 盘A"}}]
        html = report_mod._surface_scan_section(results)
    assert "最近一次" in html, "报告缺少『最近一次』字样"
    assert "无需为刷新结果而重新扫描" in html, "报告缺少结果复用说明"


if __name__ == "__main__":
    from _runner import run_module_tests
    sys.exit(run_module_tests(__name__))
