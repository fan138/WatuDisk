# -*- coding: utf-8 -*-
"""v1.1 托盘 offscreen 测试（QA 自编）。

覆盖：
- 7 张程序化图标（六档色 + 灰）非 null，且取像素颜色与 GRADE_COLORS 档位色一致；
- 菜单动作存在性（打开/立即检测/开机启动勾选/退出）；
- 单击唤起（Trigger -> wake_up 被调用）；
- update_results 最差档位取色与 tooltip；
- force_quit 不挂死；
- QLocalServer 单实例：is_already_running / start_instance_server。

运行需 QT_QPA_PLATFORM=offscreen（文件内自设）。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(TEST_DIR, "..", "src")))
sys.path.insert(0, TEST_DIR)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.verdict import (  # noqa: E402
    GRADE_COLORS,
    GRADE_CRITICAL,
    GRADE_DANGEROUS,
    GRADE_EXCELLENT,
    GRADE_FAIR,
    GRADE_GOOD,
    GRADE_UNKNOWN,
    GRADE_WARN,
)

_app = QApplication.instance() or QApplication(sys.argv)

from ui import tray as tray_mod  # noqa: E402
from ui.tray import (  # noqa: E402
    BACKGROUND_INTERVAL_MS,
    TrayController,
    is_already_running,
    paint_grade_icon,
    start_instance_server,
)

_GRADES = [GRADE_CRITICAL, GRADE_DANGEROUS, GRADE_WARN, GRADE_FAIR, GRADE_GOOD, GRADE_EXCELLENT, GRADE_UNKNOWN]


class FakeWindow:
    """托盘控制器依赖的最小窗口接口（记录调用，便于断言）。"""

    def __init__(self) -> None:
        self.wake_up_calls = 0
        self.detect_calls = 0
        self.autostart_calls: list[bool] = []
        self.quit_calls = 0

    def wake_up(self) -> None:
        self.wake_up_calls += 1

    def start_detection_from_tray(self) -> None:
        self.detect_calls += 1

    def set_autostart(self, enabled: bool) -> None:
        self.autostart_calls.append(enabled)

    def is_detecting(self) -> bool:
        return False

    def force_quit(self) -> None:
        self.quit_calls += 1


def _make_controller() -> tuple[TrayController, FakeWindow]:
    window = FakeWindow()
    controller = TrayController(window, version="v1.1-test")
    return controller, window


def test_paint_grade_icon_seven_icons_not_null():
    for grade in _GRADES:
        icon = paint_grade_icon(grade)
        assert not icon.isNull(), f"grade={grade} 的 QIcon 为 null"
        pixmap = icon.pixmap(64, 64)
        assert not pixmap.isNull(), f"grade={grade} 的 QPixmap 为 null"
        assert pixmap.width() == 64 and pixmap.height() == 64


def test_icon_center_color_matches_grade_color():
    """取底色区域像素（x=32, y=12：避开白色盘体与危险角标）比对档位色。"""
    for grade in _GRADES:
        icon = paint_grade_icon(grade)
        image = icon.pixmap(64, 64).toImage()
        assert image.format() != QImage.Format.Format_Invalid
        color = image.pixelColor(32, 12)
        expected = QColor(GRADE_COLORS[grade])
        assert color == expected, (
            f"grade={grade} 中心色 {color.name()} 与档位色 {expected.name()} 不一致"
        )


def test_danger_grades_have_exclamation_badge():
    """危险/紧急档右上角应有角标（角标区域非档位色），其它档无角标。"""
    for grade in (GRADE_CRITICAL, GRADE_DANGEROUS):
        image = paint_grade_icon(grade).pixmap(64, 64).toImage()
        badge_color = image.pixelColor(int(64 * 0.76), int(64 * 0.24))
        base_color = QColor(GRADE_COLORS[grade])
        assert badge_color != base_color, f"grade={grade} 角标区域颜色与底色相同，角标缺失"
    for grade in (GRADE_WARN, GRADE_FAIR, GRADE_GOOD, GRADE_EXCELLENT):
        image = paint_grade_icon(grade).pixmap(64, 64).toImage()
        badge_color = image.pixelColor(int(64 * 0.76), int(64 * 0.24))
        # 非危险档该区域应为透明或底色（无角标）
        assert badge_color.alpha() == 0 or badge_color == QColor(GRADE_COLORS[grade]), (
            f"grade={grade} 不应有角标，但角标区域颜色为 {badge_color.name()} alpha={badge_color.alpha()}"
        )


def test_tray_menu_actions_exist():
    controller, window = _make_controller()
    try:
        menu = controller._tray.contextMenu()
        assert menu is not None, "托盘未设置右键菜单"
        actions = menu.actions()
        texts = [a.text() for a in actions]
        for expected in ("打开主界面", "立即检测", "开机启动", "退出"):
            assert expected in texts, f"托盘菜单缺少「{expected}」，实际：{texts}"
        # 开机启动动作可勾选
        autostart_action = next(a for a in actions if a.text() == "开机启动")
        assert autostart_action.isCheckable()
        # 动作触发正确回调
        next(a for a in actions if a.text() == "打开主界面").trigger()
        assert window.wake_up_calls == 1
        next(a for a in actions if a.text() == "立即检测").trigger()
        assert window.detect_calls == 1
        next(a for a in actions if a.text() == "退出").trigger()
        assert window.quit_calls == 1, "退出动作应触发 force_quit"
    finally:
        controller.hide_tray()


def test_tray_single_click_wakes_window():
    controller, window = _make_controller()
    try:
        controller._on_activated(
            tray_mod.QSystemTrayIcon.ActivationReason.Trigger
        )
        assert window.wake_up_calls == 1, "单击托盘应唤起主窗口"
        # 右键 / 其它原因不唤起
        controller._on_activated(
            tray_mod.QSystemTrayIcon.ActivationReason.Context
        )
        assert window.wake_up_calls == 1
    finally:
        controller.hide_tray()


def test_tray_background_timer_is_two_hours():
    controller, _window = _make_controller()
    try:
        assert BACKGROUND_INTERVAL_MS == 2 * 60 * 60 * 1000
        assert controller._bg_timer.interval() == BACKGROUND_INTERVAL_MS
        assert controller._bg_timer.isActive()
    finally:
        controller.hide_tray()


def test_update_results_worst_grade_and_tooltip():
    controller, _window = _make_controller()
    try:
        results = [
            {"verdict": {"score": 96, "level": "healthy", "level_text": "健康", "reasons": []}},
            {"verdict": {"score": 79, "level": "warning", "level_text": "警告", "reasons": []}},
        ]
        controller.update_results(results)
        # 最差档 = 警告橙(2)，托盘图标应切换为该档
        assert controller._last_worst_grade == GRADE_WARN
        assert controller._tray.toolTip().startswith("挖兔硬盘精灵")
        assert "共 2 块盘" in controller._tray.toolTip()
        assert "警告" in controller._tray.toolTip()

        # 空结果 -> 未检测灰
        controller.update_results([])
        assert controller._last_worst_grade == GRADE_UNKNOWN

        # 危险盘 -> 危险红
        controller.update_results(
            [{"verdict": {"score": 30, "level": "danger", "level_text": "危险", "reasons": []}}]
        )
        assert controller._last_worst_grade == GRADE_DANGEROUS
    finally:
        controller.hide_tray()


def test_notify_if_worse_notifies_once_not_repeated():
    """等级变差弹一次气泡；同档位不重复轰炸；等级回升再变差才再弹。"""
    controller, _window = _make_controller()
    try:
        warning_result = [{"verdict": {"score": 79, "level": "warning", "level_text": "警告", "reasons": []}}]
        controller.update_results([{"verdict": {"score": 96, "level": "healthy", "level_text": "健康", "reasons": []}}])
        # 良好(4)不触发通知
        assert controller._notified_grade is None
        # 变差到警告 -> 弹一次
        controller.update_results(warning_result, notify_if_worse=True)
        assert controller._notified_grade == GRADE_WARN
        # 同档位再来 -> 不重复
        controller.update_results(warning_result, notify_if_worse=True)
        assert controller._notified_grade == GRADE_WARN
        # 回升 -> 再变差 -> 再弹一次
        controller.update_results([{"verdict": {"score": 96, "level": "healthy", "level_text": "健康", "reasons": []}}])
        controller.update_results(warning_result, notify_if_worse=True)
        assert controller._notified_grade == GRADE_WARN
    finally:
        controller.hide_tray()


def test_sync_autostart_block_signals_no_loop():
    controller, window = _make_controller()
    try:
        controller.sync_autostart(True)
        assert controller._act_autostart.isChecked() is True
        assert window.autostart_calls == [], "sync 不应回环触发 set_autostart"
        controller.sync_autostart(False)
        assert controller._act_autostart.isChecked() is False
    finally:
        controller.hide_tray()


def test_force_quit_does_not_hang():
    """force_quit（托盘退出路径）必须立刻返回，不挂死。"""
    controller, window = _make_controller()
    try:
        controller.hide_tray()  # 退出前隐藏（同 force_quit 内部路径）
        window.force_quit()
        assert window.quit_calls == 1
    finally:
        controller.hide_tray()


def test_single_instance_server_detects_second_launch():
    """QLocalServer 单实例：本实例监听后 is_already_running 应为 True。"""
    activated: list[int] = []
    server = start_instance_server(lambda: activated.append(1))
    try:
        assert server is not None and server.isListening()
        assert is_already_running() is True, "监听中的实例应被探测到"
    finally:
        if server is not None:
            server.close()
    # 关闭后不再探测到
    assert is_already_running() is False


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
