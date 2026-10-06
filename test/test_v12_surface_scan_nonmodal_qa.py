# -*- coding: utf-8 -*-
"""v1.2 盘面扫描「非模态 + 主窗口联动」回归测试（本轮五条反馈）。

锁定五件事：
1. 布局遮挡：进度条 + 状态区放在**固定高度容器**里，扫描前后整体高度不变
   （进度条显示/隐藏不再让下方文字上移）。
2. 隐藏后重开：非模态 show()，隐藏不销毁对话框；重开复用同一实例看得到进度。
3. 主按钮实时进度：scan_progress 信号把百分比回传主界面显示「扫描中 12.33%」。
4. 勾选/弹窗逻辑：全盘档**不再二次确认**；扫完**不弹 QMessageBox 硬窗**，
   改为主按钮显示「扫描完成」，点击可查看结果。
5. 隐藏差异化：隐藏时扫完只托盘提醒不强行弹回；未隐藏时结果页就在眼前。

全部离线：不触发真实磁盘读取，信号用假的线程/假的结果驱动。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.surface_scan_dialog import SurfaceScanDialog  # noqa: E402

app = QApplication.instance() or QApplication([])

_FAKE_DISKS = [
    {"device_id": "0", "model": "NVMe 盘A", "size": 1024 ** 4},
    {"device_id": "1", "model": "机械盘B", "size": 2 * 1024 ** 4},
]


def _dlg() -> SurfaceScanDialog:
    return SurfaceScanDialog(list(_FAKE_DISKS))


def _fake_result(**over) -> dict:
    base = {
        "device_id": "0",
        "mode": "quick",
        "finished": True,
        "cancelled": False,
        "error": "",
        "bytes_scanned": 1600 * 1024 * 1024,
        "elapsed_sec": 1.2,
        "speed_mb_s": 1300.0,
        "chunks_ok": 400,
        "chunks_failed": 0,
        "cells": [1] * 400,
        "cells_scanned": 400,
        "slow_cells": 0,
        "very_slow_cells": 0,
        "bad_cells": 0,
        "baseline_ms": 1.0,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- 1. 布局遮挡

def test_scan_area_fixed_height():
    """进度条显隐不改变整块高度——这是「扫描中区域变形、下方文字上移」的修复点。"""
    d = _dlg()
    assert d._scan_area.minimumHeight() == d._scan_area.maximumHeight(), \
        "扫描信息区必须固定高度，否则进度条显隐会顶动布局"
    h = d._scan_area.minimumHeight()
    assert d._bar.isHidden() is True
    d._enter_scanning()
    assert d._bar.isHidden() is False
    assert d._scan_area.minimumHeight() == h, "进度条显示后扫描区高度被改动了"
    d._enter_idle("重新扫描")
    assert d._bar.isHidden() is True
    assert d._scan_area.minimumHeight() == h, "进度条隐藏后扫描区高度被改动了"


def test_status_reserves_two_lines():
    """状态文字有最小高度，长文案换行时不会把下方按钮顶走。"""
    d = _dlg()
    assert d._status.minimumHeight() >= 34, d._status.minimumHeight()
    assert d._status.wordWrap() is True


# ---------------------------------------------------------------- 2. 隐藏与重开

def test_hide_then_reopen_keeps_progress():
    """隐藏后再 show：仍是同一个对话框，且扫描进度保留（不是全新界面）。"""
    d = _dlg()
    d._enter_scanning()
    d._grid.set_state(7, 1)
    d._update_grid_info()
    seen_before = d._grid.scanned_count()
    d._on_secondary()  # 隐藏
    try:
        assert d.isHidden() is True
        assert d._was_hidden is True
        d.showNormal()  # 重新点开
        assert d._grid.scanned_count() == seen_before, "重开后盘面格子应保留，不应被清空"
        assert "已扫 1 / 400 格" == d._grid_count.text(), d._grid_count.text()
    finally:
        d.hide()


def test_hidden_does_not_finish_dialog():
    """隐藏不销毁对话框：_scanning 仍为真，后台线程还在跑。"""
    d = _dlg()
    d._enter_scanning()
    d._on_secondary()
    try:
        assert d._scanning is True
    finally:
        d._enter_idle("重新扫描")


# ---------------------------------------------------------------- 3. 主按钮实时进度

def test_progress_signal_emits_percent():
    """进度回调把百分比回传给主窗口（用于「扫描中 12.33%」实时显示）。"""
    d = _dlg()
    got: list[float] = []
    d.scan_progress.connect(got.append)
    d._on_progress(512 * 1024 * 1024, 1024 * 1024 * 1024, 0)
    assert got, "没有发出 scan_progress 信号"
    assert abs(got[-1] - 50.0) < 0.01, got[-1]
    assert "50.00%" in d._status.text(), d._status.text()


def test_progress_signal_handles_zero_planned():
    """planned 为 0 时不能除零崩溃。"""
    d = _dlg()
    got: list[float] = []
    d.scan_progress.connect(got.append)
    d._on_progress(0, 0, 0)
    assert got and got[-1] == 0.0, got


def test_state_signals_sequence():
    """会话状态信号：进入扫描发 scanning，收尾发 finished。"""
    d = _dlg()
    states: list[str] = []
    d.scan_state_changed.connect(states.append)
    d._enter_scanning()
    assert "scanning" in states, states
    d._queue = []
    d._total_in_chain = 1
    d._after_result_dialog()
    assert states[-1] == "finished", states


# ---------------------------------------------------------------- 4. 勾选/弹窗逻辑

def test_full_mode_no_second_confirmation():
    """全盘档点开始扫描**不再弹二次确认**（耗时风险已写在估算文案里）。"""
    import inspect
    import ui.surface_scan_dialog as mod

    src = inspect.getsource(mod.SurfaceScanDialog._on_start)
    assert "QMessageBox.question" not in src, "全盘档仍在弹二次确认，用户明确要求免确认"
    # 只允许保留「没勾选任何盘」这一种提示
    assert src.count("QMessageBox") == 1, src.count("QMessageBox")
    assert "请先勾选" in src


def test_finish_shows_panel_not_messagebox():
    """扫完走美化结果页，不弹 QMessageBox 硬窗。"""
    d = _dlg()
    d._enter_scanning()
    d._current_disk = dict(_FAKE_DISKS[0])
    d._total_in_chain = 1
    d._done_in_chain = 1
    d._queue = []
    d._show_result_panel("good", "未发现读失败或明显偏慢的区域", _fake_result())
    assert d._result_panel.isHidden() is False, "结果页应显示"
    assert "盘面扫描完成" in d._result_title.text(), d._result_title.text()
    assert "无需重新扫描" in d._result_note.text()
    # 结果页样式带左侧色条
    assert "resultCard" in d._result_panel.styleSheet()


def test_result_panel_level_colors_differ():
    """good / bad 结论的结果页左边条颜色不同，一眼能看出好坏。"""
    d = _dlg()
    d._show_result_panel("good", "正常", _fake_result())
    good_css = d._result_panel.styleSheet()
    d._show_result_panel("bad", "发现坏道", _fake_result(bad_cells=3, cells_failed=3))
    bad_css = d._result_panel.styleSheet()
    assert good_css != bad_css


def test_scan_start_hides_result_panel():
    """重新开始扫描时，上一轮的结果页要收起来，不能和新进度混在一起。"""
    d = _dlg()
    d._show_result_panel("good", "正常", _fake_result())
    assert d._result_panel.isHidden() is False
    d._enter_scanning()
    assert d._result_panel.isHidden() is True


# ---------------------------------------------------------------- 5. 隐藏差异化

def test_hidden_finish_only_tray_no_forced_show():
    """隐藏状态下扫完：不强行弹回窗口，只托盘提醒。"""
    notices: list[tuple] = []

    class _Tray:
        def notify_custom(self, title, text, icon=None):
            notices.append((title, text))

    d = SurfaceScanDialog(list(_FAKE_DISKS), tray=_Tray())
    d._enter_scanning()
    d._current_disk = dict(_FAKE_DISKS[0])
    d._total_in_chain = 1
    d._done_in_chain = 1
    d._queue = []
    d._on_secondary()  # 隐藏
    assert d.isHidden() is True
    d._on_finished(_fake_result())
    try:
        # 仍然隐藏——不打扰用户
        assert d._was_hidden is False, "隐藏标记应被消费"
        assert notices, "隐藏扫完应至少有一条托盘提醒"
        assert "点击主界面" in notices[-1][1], notices[-1][1]
    finally:
        d._enter_idle("重新扫描")


def test_hidden_chain_only_notifies_on_last_disk():
    """多盘连扫且隐藏时：中间盘不打扰，全部扫完才提醒一次。"""
    notices: list[tuple] = []

    class _Tray:
        def notify_custom(self, title, text, icon=None):
            notices.append((title, text))

    d = SurfaceScanDialog(list(_FAKE_DISKS), tray=_Tray())
    d._enter_scanning()
    d._current_disk = dict(_FAKE_DISKS[0])
    d._total_in_chain = 2
    d._done_in_chain = 1
    d._queue = ["1"]  # 还有一块没扫
    d._on_secondary()
    notices.clear()
    d._on_finished(_fake_result())
    try:
        assert notices == [], f"中间盘不该弹提醒，避免打扰：{notices}"
    finally:
        d._enter_idle("重新扫描")


def test_not_hidden_finish_keeps_dialog_visible():
    """未隐藏时扫完：对话框就在眼前，结果页直接可见。"""
    d = _dlg()
    d.showNormal()
    d._enter_scanning()
    d._current_disk = dict(_FAKE_DISKS[0])
    d._total_in_chain = 1
    d._done_in_chain = 1
    d._queue = []
    d._on_finished(_fake_result())
    try:
        assert d.isHidden() is False
        assert d._result_panel.isHidden() is False
    finally:
        d._enter_idle("重新扫描")
        d.hide()


def test_close_when_idle_resets_state_signal():
    """空闲态关闭对话框要发 idle，让主窗口按钮复位。"""
    d = _dlg()
    states: list[str] = []
    d.scan_state_changed.connect(states.append)
    d._enter_idle("重新扫描")
    d.close()
    assert states and states[-1] == "idle", states


if __name__ == "__main__":
    from _runner import run_module_tests
    sys.exit(run_module_tests(__name__))
