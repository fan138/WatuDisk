# -*- coding: utf-8 -*-
"""离屏 GUI 内存测量辅助：创建主窗口并跑完整检测，停留 40 秒供外部采样。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\Projects\DiskGuard\src")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

app = QApplication(sys.argv)
window = MainWindow(admin=True, version="measure", enable_tray=False)
window.show()
# 40 秒后自动退出（检测约 20-35 秒）
window._force_close = True
__import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer.singleShot(40_000, app.quit)
sys.exit(app.exec())
