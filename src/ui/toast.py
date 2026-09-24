# -*- coding: utf-8 -*-
"""自绘通知气泡（v1.6）：不依赖 Windows 通知系统，勿扰模式也拦不住。

特性：
- 仿 Win11 卡片样式：白底圆角卡片 + 档位色图标块 + 标题/正文 + 关闭钮；
- 出现：从下往上滑入 + 渐显（250ms）；停留 5 秒后渐隐自动关闭
  （危险级停留 8 秒）；
- 点击卡片打开主界面；点 ✕ 立即关闭；
- 不抢焦点（ShowWithoutActivating）、置顶显示、右下角托盘上方堆叠
  （最多 3 张，超出立即淘汰最旧）；
- 纯本地绘制，不写盘、不联网。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# 级别 -> 图标块底色
LEVEL_COLORS = {"info": "#1FAF52", "warn": "#DD6B1D", "danger": "#C93A3A"}

# 停留时长（毫秒）
STAY_MS = {"info": 5000, "warn": 6000, "danger": 8000}

MAX_ACTIVE = 3


class ToastPopup(QFrame):
    """单张自绘气泡卡片。"""

    closed = Signal(object)   # 关闭后通知 manager 重排（self 传出）

    def __init__(self, level: str, title: str, text: str, on_click=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(340)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._level = level if level in LEVEL_COLORS else "info"
        self._on_click = on_click
        self._closing = False

        card = QFrame(self)
        card.setObjectName("toastCard")
        card.setStyleSheet(
            "#toastCard { background: #F7F8FA; border: 1px solid #E0E2E8;"
            " border-radius: 10px; }"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 11, 10, 11)
        row.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background:{LEVEL_COLORS[self._level]}; border-radius:8px;"
            " color:#FFFFFF; font-weight:700; font-size:15px;"
        )
        icon.setText("!" if self._level != "info" else "✓")
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("color:#5F5E5A; font-size:12px; background:transparent;")
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet("color:#1F2937; font-size:13px; font-weight:500; background:transparent;")
        col.addWidget(title_label)
        col.addWidget(text_label)
        row.addLayout(col, 1)

        close_btn = QLabel("✕")
        close_btn.setFixedWidth(16)
        close_btn.setAlignment(Qt.AlignmentFlag.AlignTop)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("color:#9CA3AF; font-size:12px; background:transparent;")
        close_btn.mousePressEvent = lambda _e: self.close_toast()  # noqa: N802
        row.addWidget(close_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

    # ------------------------------------------------------------------
    def place(self, index: int) -> None:
        """摆在屏幕右下角（第 index 张向上叠加）。"""
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else self.screen().availableGeometry()
        self.adjustSize()
        margin = 14
        x = geo.right() - self.width() - margin
        y = geo.bottom() - self.height() - margin - index * (self.height() + 8)
        self._target_pos = (x, y)
        self.move(x, y + 18)  # 起点略低，滑入

    def show_toast(self) -> None:
        self.show()
        x, y = getattr(self, "_target_pos", (self.x(), self.y()))
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(250)
        slide.setStartValue(self.pos())
        slide.setEndValue(type(self.pos())(x, y))
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade = QPropertyAnimation(self._opacity, b"opacity", self)
        fade.setDuration(250)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        QTimer.singleShot(STAY_MS.get(self._level, 5000), self.close_toast)

    def close_toast(self) -> None:
        """渐隐关闭；重复触发安全。"""
        if self._closing:
            return
        self._closing = True
        fade = QPropertyAnimation(self._opacity, b"opacity", self)
        fade.setDuration(280)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)

        def _done() -> None:
            self.closed.emit(self)
            self.close()
            self.deleteLater()

        fade.finished.connect(_done)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        """点击卡片：打开主界面并关闭气泡。"""
        if self._on_click is not None:
            try:
                self._on_click()
            except Exception:
                pass
        self.close_toast()
        super().mousePressEvent(event)


class ToastManager(QObject):
    """气泡堆叠管理：右下角最多同时 3 张，新气泡向上排。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._active: list[ToastPopup] = []

    def push(self, level: str, title: str, text: str, on_click=None) -> None:
        """弹出一张气泡；超出上限时立即淘汰最旧。"""
        # 清理已结束的
        self._active = [t for t in self._active if t.isVisible()]
        while len(self._active) >= MAX_ACTIVE:
            oldest = self._active.pop(0)
            oldest.close_toast()
        toast = ToastPopup(level, title, text, on_click=on_click)
        toast.closed.connect(self._on_closed)
        self._active.append(toast)
        toast.place(len(self._active) - 1)
        toast.show_toast()

    def _on_closed(self, toast: object) -> None:
        if toast in self._active:
            self._active.remove(toast)

    def close_all(self) -> None:
        for toast in list(self._active):
            toast.close_toast()
        self._active.clear()
