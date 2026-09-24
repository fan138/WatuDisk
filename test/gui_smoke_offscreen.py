# -*- coding: utf-8 -*-
"""独立 Qt 冒烟测试（offscreen 平台）：
实例化主窗口 -> 等待一次完整检测流程结束 -> 断言结果卡片数量与本机物理盘数一致 -> 延迟 2.5 秒后自动退出。

注意：本机完整检测约需 15-20 秒（PowerShell 多次调用），必须等 detect_finished
信号后再退出；提前退出会杀死后台 QThread 导致 0xC0000409 崩溃。
"""
from __future__ import annotations

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # 必须在导入 PySide6 之前设置

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.disk_info import get_physical_disks  # noqa: E402
from ui.main_window import DiskCard, MainWindow  # noqa: E402


def count_disk_cards(window: MainWindow) -> int:
    """统计滚动区里 DiskCard 的数量。"""
    return sum(
        1
        for i in range(window._list_layout.count())
        if isinstance(window._list_layout.itemAt(i).widget(), DiskCard)
    )


def main() -> int:
    expected = len(get_physical_disks())
    print(f"[smoke] 本机物理盘数（基准）: {expected}")

    app = QApplication(sys.argv)
    window = MainWindow(admin=True, version="v1.0")
    window.show()

    state = {"finished": False, "ok": False, "waited_ms": 0}

    def check() -> None:
        """轮询等待检测完成；90 秒超时判失败。"""
        state["waited_ms"] += 500
        if state["finished"]:
            cards = count_disk_cards(window)
            total_text = window._ov_total.text()
            print(f"[smoke] 检测完成信号已收到，DiskCard 数量: {cards}，概览总数: {total_text}")
            state["ok"] = cards == expected and total_text == str(expected)
            if not state["ok"]:
                print(f"[smoke][FAIL] 卡片数 {cards} != 期望 {expected} 或概览数不对")
            else:
                print("[smoke] 卡片数量与本机物理盘数一致")
            # 断言完成后停留 2.5 秒再退出（满足"展示 2-3 秒"要求，也让动画/线程收尾）
            QTimer.singleShot(2500, app.quit)
        elif state["waited_ms"] > 90000:
            print("[smoke][FAIL] 90 秒内未收到检测完成信号")
            state["ok"] = False
            app.quit()
        else:
            QTimer.singleShot(500, check)

    window._worker.detect_finished.connect(lambda _results: state.__setitem__("finished", True))
    QTimer.singleShot(500, check)
    app.exec()

    # 收尾：确保后台线程已退出再离开进程
    if window._worker is not None and window._worker.isRunning():
        window._worker.wait(5000)

    print(f"[smoke] 结果: {'PASS' if state['ok'] else 'FAIL'}")
    return 0 if state["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
