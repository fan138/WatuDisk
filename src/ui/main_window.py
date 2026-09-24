# -*- coding: utf-8 -*-
"""挖兔硬盘精灵 主窗口：紧凑单窗口布局 + QThread 后台检测 + 360 式体检动效。

界面结构：
- 顶部标题栏：软件名 + 版本 + 「绿色版·离线」徽章 + 管理员状态；
- 概览行：3 个指标卡（检测到硬盘 / 健康 / 警告+危险）；
- 磁盘卡片列表：点击展开详情（专业指标网格 + SMART 表格 + 事件摘要 + 建议）；
- 底部：7 步体检步骤清单（待办灰点 -> 旋转 spinner -> 绿色✓ / 橙色!）
  + 平滑动画进度条 + 药丸按钮 + 开机启动开关 + 「只读检测」小字。

检测全程在 QThread 后台线程执行，UI 绝不卡顿；卡片渐入使用透明度动画。
v1.1：关闭主窗口最小化到托盘、开机启动（绿色方式）、专业指标展示。
"""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import autostart, event_scan, metrics, notify_policy, report, verdict
from core.disk_info import format_hours_pro, format_int, format_size
from core.nvme_health import format_data_units
from core.resource_path import app_icon_path
from core.store import get_store
from core.verdict import GRADE_LABELS, grade_of_verdict
from ui.theme import QSS

# 结论 -> (药丸样式 objectName, 药丸文字)（v1.0 三档语义保留作回退）
LEVEL_PILL = {
    "healthy": ("pillHealthy", "健康"),
    "warning": ("pillWarning", "警告"),
    "danger": ("pillDanger", "危险"),
}

# Get-PhysicalDisk HealthStatus 的中文显示
HEALTH_TEXT = {"healthy": "良好", "warning": "警告", "unhealthy": "不健康"}

# 项目主页（点击底部「GitHub」按钮用系统默认浏览器打开）
GITHUB_URL = "https://github.com/fan138/WatuDisk"

# 高亮的危险 SMART 属性
_BAD_ATTR_IDS = (0x05, 0xC5, 0xC6, 0xC7)


def _bus_text(bus: str) -> str:
    """接口类型显示名。"""
    mapping = {"NVME": "NVMe", "SATA": "SATA", "USB": "USB", "SAS": "SAS", "RAID": "RAID"}
    return mapping.get(str(bus).upper(), bus or "未知")


def _media_text(media: str, bus: str) -> str:
    """介质类型显示名。"""
    m = str(media).upper()
    if m == "SSD":
        return "SSD"
    if m == "HDD":
        return "HDD"
    if str(bus).upper() == "NVME":
        return "SSD"
    return "硬盘"


def _fade_in(widget: QWidget) -> None:
    """透明度渐入动画（卡片出现效果）。"""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(380)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def _fade_out_then_hide(widget: QWidget, duration: int = 600) -> None:
    """透明度渐出动画，结束后隐藏 widget（体检清单收场）。"""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.Type.InCubic)

    def _hide() -> None:
        widget.setVisible(False)
        widget.setGraphicsEffect(None)

    animation.finished.connect(_hide)
    animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def _repolish(widget: QWidget) -> None:
    """修改 objectName 后强制刷新 QSS 样式。"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class DetectWorker(QThread):
    """后台检测线程：7 步流程，每步发 step_started / step_result 信号。

    全部只读、不写盘；单步失败只标记该步（橙色 !），后续步骤继续。
    """

    step_started = Signal(int)
    step_result = Signal(int, bool, str)
    disks_enumerated = Signal(list)   # v1.8：步骤 0 完成即推出硬盘基础信息（骨架卡片）
    detect_finished = Signal(list)
    detect_failed = Signal(str)

    # 固定 7 步：索引与界面步骤清单一一对应
    STEPS = (
        "枚举硬盘设备",
        "读取健康状态",
        "解析 SMART 属性",
        "读取温度与寿命",
        "扫描系统事件日志",
        "检查卷损坏标志",
        "生成评分与建议",
    )

    def run(self) -> None:
        try:
            results = self._detect()
            self.detect_finished.emit(results)
        except Exception as exc:  # 兜底：任何异常都不允许直接崩溃
            self.detect_failed.emit(str(exc))

    def _emit_result(self, index: int, ok: bool, summary: str) -> None:
        self.step_result.emit(index, ok, summary)

    def _detect(self) -> list[dict]:
        from core import disk_info, nvme_health, smart_parser, volume_check

        # ---- 步骤 0：枚举硬盘设备 ----
        self.step_started.emit(0)
        disks = disk_info.get_physical_disks()
        if disks:
            self._emit_result(0, True, f"发现 {len(disks)} 块硬盘")
            self.disks_enumerated.emit(list(disks))  # v1.8：立即显示硬盘条目
        else:
            self._emit_result(0, False, "未发现任何硬盘设备（可能权限不足）")

        # ---- 步骤 1：读取健康状态（Get-PhysicalDisk 已随枚举返回） ----
        self.step_started.emit(1)
        health_counts: dict[str, int] = {}
        for disk in disks:
            key = str(disk.get("health_status") or "Unknown").lower()
            health_counts[key] = health_counts.get(key, 0) + 1
        if disks:
            parts = [
                f"{count} 块{HEALTH_TEXT.get(key, key)}"
                for key, count in health_counts.items()
            ]
            self._emit_result(1, True, "系统报告：" + "、".join(parts))
        else:
            self._emit_result(1, False, "无法读取系统健康状态")

        # ---- 步骤 2：解析 SMART 属性（SATA 盘；NVMe 走直读健康日志通道） ----
        self.step_started.emit(2)
        smart_map = smart_parser.get_smart_for_disks(disks)
        sata_count = sum(
            1
            for disk in disks
            if str(disk.get("bus_type") or "").upper() not in ("NVME", "USB")
        )
        if sata_count == 0:
            self._emit_result(2, True, "本机无 SATA 盘，NVMe 走直读健康日志通道")
        elif smart_map:
            self._emit_result(2, True, f"已解析 {len(smart_map)} 块 SATA 盘的 SMART 属性")
        else:
            self._emit_result(2, False, "无法读取 SMART 属性（权限不足或系统不支持）")

        # ---- 步骤 3：读取温度与寿命（可靠性计数器 + NVMe 健康日志直读） ----
        self.step_started.emit(3)
        counters_map = disk_info.get_reliability_counters()
        nvme_map: dict[str, dict] = {}
        for disk in disks:
            try:
                drive_number = int(str(disk.get("device_id") or ""))
            except (TypeError, ValueError):
                continue
            health = nvme_health.query_nvme_health(drive_number)
            if health is not None:
                nvme_map[str(disk.get("device_id") or "")] = health
        if counters_map:
            temp_count = sum(
                1
                for counters in counters_map.values()
                if isinstance(counters.get("Temperature"), int) and counters["Temperature"] > 0
            )
            detail = f"，其中 {temp_count} 块盘可读温度" if temp_count else ""
            message = f"已读取 {len(counters_map)} 块盘的可靠性计数器{detail}"
            if nvme_map:
                message += f"；NVMe 健康日志直读成功 {len(nvme_map)} 块"
            self._emit_result(3, True, message)
        elif nvme_map:
            self._emit_result(
                3, True, f"可靠性计数器不可读，已直读 NVMe 健康日志获得 {len(nvme_map)} 块盘数据"
            )
        else:
            self._emit_result(3, False, "无法读取可靠性计数器（需要管理员权限）")

        # ---- 步骤 4：扫描系统事件日志 ----
        self.step_started.emit(4)
        events = event_scan.scan_disk_events()
        self._emit_result(4, True, f"读取 {len(events)} 条磁盘相关错误/警告日志")

        # ---- 步骤 5：检查卷损坏标志 + 剩余空间（v1.4） ----
        self.step_started.emit(5)
        volumes = volume_check.check_volumes()
        if volumes:
            dirty_count = sum(1 for v in volumes if v.get("dirty"))
            space_bits = [
                f"{v.get('drive')} {v.get('free_pct')}%"
                for v in volumes
                if isinstance(v.get("free_pct"), (int, float))
            ]
            space_text = f"；剩余空间：{'、'.join(space_bits)}" if space_bits else ""
            if dirty_count:
                self._emit_result(5, True, f"扫描 {len(volumes)} 个卷，{dirty_count} 个卷损坏位已置位{space_text}")
            else:
                self._emit_result(5, True, f"扫描 {len(volumes)} 个卷，损坏位均未置位{space_text}")
        else:
            self._emit_result(5, False, "无法读取卷损坏标志（需要管理员权限）")

        # ---- 步骤 6：生成评分与建议 ----
        self.step_started.emit(6)
        results: list[dict] = []
        for disk in disks:
            device_id = str(disk.get("device_id") or "")
            counters = counters_map.get(device_id)
            attrs = smart_map.get(device_id, [])
            event_count, event_recent = event_scan.match_events_to_disk(events, disk)
            # 卷归因：跨盘卷（Storage Spaces）的 disk_numbers 可关联多个物理盘，
            # 任何关联盘都计入该盘的卷列表
            disk_volumes = []
            for volume in volumes:
                numbers = volume.get("disk_numbers")
                if numbers is None:
                    single = volume.get("disk_number")
                    numbers = [single] if single is not None else []
                if any(str(n) == device_id for n in numbers):
                    disk_volumes.append(volume)
            dirty = [v for v in disk_volumes if v.get("dirty")]
            results.append(
                {
                    "disk": disk,
                    "counters": counters,
                    "nvme_health": nvme_map.get(device_id),
                    "smart_attrs": attrs,
                    "event_count": event_count,
                    "event_recent": event_recent,
                    "dirty_volumes": dirty,
                    "all_volumes": disk_volumes,
                    "verdict": verdict.evaluate_disk(
                        disk, counters, attrs, event_count, event_recent, dirty,
                        nvme_map.get(device_id),
                    ),
                }
            )
        self._emit_result(6, True, f"已生成 {len(results)} 块盘的健康评分与建议")
        return results


class DetectStepsWidget(QWidget):
    """360 式体检步骤清单：固定 7 步状态机 + spinner 动画。

    状态：待办（灰点 ○）-> 进行中（旋转 spinner）-> 完成（✓ + 结果摘要）
    或失败（橙色 ! + 简短原因）。全部完成后整体淡出收场。
    """

    SPINNER_FRAMES = ("◐", "◓", "◑", "◒")
    _TICK_MS = 120
    _COLLAPSE_DELAY_MS = 1400

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running = -1
        self._frame = 0

        self._card = QFrame(self)
        self._card.setObjectName("stepsCard")
        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(1)

        self._row_labels: list[QLabel] = []
        for index, name in enumerate(DetectWorker.STEPS):
            label = QLabel(self._pending_text(index))
            label.setObjectName("stepRow")
            layout.addWidget(label)
            self._row_labels.append(label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._card)

        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(self._TICK_MS)
        self._spinner_timer.timeout.connect(self._on_tick)

        self.setVisible(False)

    # ------------------------------------------------------------------
    def _pending_text(self, index: int) -> str:
        return f"○  {index + 1}. {DetectWorker.STEPS[index]}"

    @staticmethod
    def _set_state(label: QLabel, object_name: str, text: str) -> None:
        label.setObjectName(object_name)
        label.setText(text)
        _repolish(label)

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """开始新一轮检测：显示全部步骤并复位为待办。"""
        self.setVisible(True)
        self._card.setVisible(True)
        for index in range(len(self._row_labels)):
            self._set_state(self._row_labels[index], "stepRow", self._pending_text(index))
        self._running = -1
        self._frame = 0
        self._spinner_timer.stop()

    def step_started(self, index: int) -> None:
        """某一步进入进行中：spinner 开始旋转。"""
        if not (0 <= index < len(self._row_labels)):
            return
        self._running = index
        self._frame = 0
        self._spinner_timer.start()
        self._set_state(
            self._row_labels[index],
            "stepRowRunning",
            f"{self.SPINNER_FRAMES[0]}  {index + 1}. {DetectWorker.STEPS[index]}…",
        )

    def step_result(self, index: int, ok: bool, summary: str) -> None:
        """某一步完成 / 失败：定格为 ✓（绿）或 !（橙）并附摘要。"""
        if not (0 <= index < len(self._row_labels)):
            return
        if index == self._running:
            self._running = -1
            self._spinner_timer.stop()
        name = DetectWorker.STEPS[index]
        if ok:
            self._set_state(
                self._row_labels[index], "stepRowDone", f"✓  {index + 1}. {name} —— {summary}"
            )
        else:
            self._set_state(
                self._row_labels[index], "stepRowFailed", f"!  {index + 1}. {name} —— {summary}"
            )

    def _on_tick(self) -> None:
        """spinner 转动：刷新进行中步骤的前置字符。"""
        self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
        if 0 <= self._running < len(self._row_labels):
            index = self._running
            self._row_labels[index].setText(
                f"{self.SPINNER_FRAMES[self._frame]}  {index + 1}. {DetectWorker.STEPS[index]}…"
            )

    def finish(self, elapsed_seconds: float) -> None:
        """全部完成：停表，稍后整体淡出（一行总结由 stage label 承接）。"""
        self._spinner_timer.stop()
        self._running = -1
        QTimer.singleShot(self._COLLAPSE_DELAY_MS, lambda: _fade_out_then_hide(self._card))


class HistoryPanel(QFrame):
    """体检记录面板（v1.3）：留下健康痕迹，支持折叠 / 展开。

    - 每次体检（手动 / 定时 / 开机静默）完成后追加一条记录；
    - 全部健康显示绿色 ✓；有警告显示黄色 !；危险显示红色 ✗；
    - 记录持久化在本地 data 文件（封顶 200 条自动淘汰最旧），
      内存占用恒定，不随使用时间增长；
    - 默认折叠不占地方，折叠状态会被记住。
    """

    MAX_DISPLAY_ROWS = 30

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyCard")
        self._store = get_store()
        self._expanded = bool(self._store.get_setting("history_expanded", False))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        self._title = QLabel("体检记录")
        self._title.setObjectName("historyHeader")
        self._count_label = QLabel("")
        self._count_label.setObjectName("note")
        self._toggle_btn = QPushButton(("▾ 收起" if self._expanded else "▸ 展开"))
        self._toggle_btn.setObjectName("historyToggle")
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._on_toggle)
        header.addWidget(self._title)
        header.addWidget(self._count_label)
        header.addStretch()
        header.addWidget(self._toggle_btn)
        outer.addLayout(header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(1)
        outer.addWidget(self._body)
        self._body.setVisible(self._expanded)

        self.refresh()

    # ------------------------------------------------------------------
    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        self._store.set_setting("history_expanded", self._expanded)
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText("▾ 收起" if self._expanded else "▸ 展开")

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """从存储重新渲染记录列表（新在前，最多显示 30 条）。

        每条记录可点击展开 / 收起当时的逐盘详情快照。
        """
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        history = self._store.history()
        self._count_label.setText(f"共 {len(history)} 次")
        if not history:
            empty = QLabel("暂无体检记录 —— 完成一次检测后，这里会留下健康痕迹。")
            empty.setObjectName("historyEmpty")
            self._body_layout.addWidget(empty)
            return
        for entry in history[: self.MAX_DISPLAY_ROWS]:
            row = QLabel(self._row_text(entry))
            level = str(entry.get("level") or "ok")
            row.setObjectName(
                "historyRowBad" if level == "danger"
                else "historyRowWarn" if level == "warning"
                else "historyRowOk"
            )
            row.setWordWrap(True)
            detail_lines = [str(x) for x in (entry.get("detail") or []) if str(x)]
            if detail_lines:
                row.setCursor(Qt.CursorShape.PointingHandCursor)
                row.setToolTip("点击展开 / 收起本次体检的逐盘详情")
                detail_label = QLabel("\n".join(f"　· {line}" for line in detail_lines))
                detail_label.setObjectName("historyDetail")
                detail_label.setWordWrap(True)
                detail_label.setVisible(False)

                def _toggle_row(label: QLabel = row, panel: QLabel = detail_label) -> None:
                    panel.setVisible(not panel.isVisible())
                    _repolish(label)

                row.mousePressEvent = lambda _event, cb=_toggle_row: cb()  # noqa: N802
                self._body_layout.addWidget(row)
                self._body_layout.addWidget(detail_label)
            else:
                self._body_layout.addWidget(row)

    @staticmethod
    def _row_text(entry: dict) -> str:
        level = str(entry.get("level") or "ok")
        icon = "✗" if level == "danger" else "！" if level == "warning" else "✓"
        parts = [
            f"{icon} {entry.get('time') or ''}",
            str(entry.get("text") or ""),
        ]
        source = str(entry.get("source") or "")
        if source and source != "手动体检":
            parts.append(f"[{source}]")
        return "  ·  ".join(part for part in parts if part)


class DiskCard(QFrame):
    """单块磁盘的卡片，点击可展开 / 收起检测详情。"""

    def __init__(
        self, result: dict, parent: QWidget | None = None, admin: bool = False,
        tip_seed: int = 0, loading: bool = False,
    ) -> None:
        super().__init__(parent)
        self._admin = admin
        self._tip_seed = tip_seed
        self._loading = loading
        self._result = result
        disk = result.get("disk") or {}
        verdict_data = result.get("verdict") or {}
        level = str(verdict_data.get("level") or "warning")
        self.setObjectName("diskCardDanger" if level == "danger" else "diskCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._score_timer: QTimer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # ---- 头部行：图标块 + 名称/摘要 + 状态药丸（六档色细化） ----
        header = QHBoxLayout()
        header.setSpacing(10)

        media = _media_text(str(disk.get("media_type") or ""), str(disk.get("bus_type") or ""))
        icon = QLabel(media)
        icon.setObjectName("diskIconSSD" if media == "SSD" else "diskIconHDD")
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(str(disk.get("model") or "未知型号"))
        name.setObjectName("diskName")
        name.setWordWrap(True)
        sub = QLabel(self._subtitle(result))
        sub.setObjectName("diskSub")
        text_col.addWidget(name)
        text_col.addWidget(sub)
        self._sub_label = sub

        pill = QLabel(self._pill_text(verdict_data))
        pill.setObjectName(self._pill_object_name(verdict_data))
        self._pill_label = pill

        header.addWidget(icon)
        header.addLayout(text_col, 1)
        header.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        # ---- 详情区（默认收起） ----
        self._detail = self._build_detail(result) if not loading else self._build_loading_detail()
        self._detail.setVisible(False)
        layout.addWidget(self._detail)

    # ------------------------------------------------------------------
    def _build_loading_detail(self) -> QWidget:
        """骨架卡片的占位详情（体检完成后由 apply_result 替换）。"""
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(4, 0, 4, 0)
        tip = QLabel("正在体检，完成后这里会显示详细指标与建议…")
        tip.setObjectName("emptyTip")
        lay.addWidget(tip)
        return holder

    def apply_result(self, result: dict) -> None:
        """体检完成：骨架卡片原地填充（v1.8）——评分 0→最终值 1.5 秒滚动。

        同时刷新副标题（温度/寿命/通电时间）、危险红边与详情面板。
        """
        self._result = result
        self._loading = False
        disk = result.get("disk") or {}
        verdict_data = result.get("verdict") or {}
        level = str(verdict_data.get("level") or "warning")
        self.setObjectName("diskCardDanger" if level == "danger" else "diskCard")
        _repolish(self)

        # 副标题补全（温度/寿命/通电时间）
        self._sub_label.setText(self._subtitle(result))

        # 详情面板重建（替换占位）
        layout = self.layout()
        old_index = layout.indexOf(self._detail)
        layout.removeWidget(self._detail)
        self._detail.deleteLater()
        self._detail = self._build_detail(result)
        self._detail.setVisible(False)
        layout.insertWidget(old_index if old_index >= 0 else layout.count(), self._detail)

        # 评分滚动：0 → 最终值，1.5 秒（OutCubic 缓动，网页同款数字滚动效果）
        self._start_score_animation(int(verdict_data.get("score") or 0), verdict_data)

    def apply_failed(self) -> None:
        """体检失败：骨架卡片标记未完成。"""
        self._loading = False
        self._pill_label.setText("未完成")
        self._pill_label.setObjectName("pillGray")
        _repolish(self._pill_label)

    def _start_score_animation(self, final_score: int, verdict_data: dict) -> None:
        """评分从 0 滚动到最终值（1.5 秒，OutCubic）。"""
        grade = grade_of_verdict(verdict_data)
        label = GRADE_LABELS.get(grade, "")
        self._pill_label.setObjectName(f"pillGrade{grade}")
        _repolish(self._pill_label)

        if self._score_timer is not None:
            self._score_timer.stop()
        if final_score <= 0:
            self._pill_label.setText(f"{label} · 0 分")
            return

        duration_ms = 1500
        tick_ms = 30
        ticks = max(1, duration_ms // tick_ms)
        state = {"tick": 0}

        def _tick() -> None:
            state["tick"] += 1
            p = min(1.0, state["tick"] / ticks)
            eased = 1.0 - (1.0 - p) ** 3  # OutCubic：先快后慢，更像网页计数效果
            value = int(round(final_score * eased))
            self._pill_label.setText(f"{label} · {value} 分")
            if p >= 1.0:
                self._pill_label.setText(f"{label} · {final_score} 分")
                if self._score_timer is not None:
                    self._score_timer.stop()

        self._score_timer = QTimer(self)
        self._score_timer.setInterval(tick_ms)
        self._score_timer.timeout.connect(_tick)
        self._score_timer.start()

    # ------------------------------------------------------------------
    @staticmethod
    def _pill_object_name(verdict_data: dict) -> str:
        """六档色药丸样式名；无效数据回退三档 / 灰。"""
        level = str(verdict_data.get("level") or "")
        if not verdict_data.get("score") and level not in LEVEL_PILL:
            return "pillGray"
        return f"pillGrade{grade_of_verdict(verdict_data)}"

    def _pill_text(self, verdict_data: dict) -> str:
        """药丸文字：六档短标签 + 分数；加载中显示「检测中」；无效数据回退。"""
        if getattr(self, "_loading", False):
            return "检测中"
        level = str(verdict_data.get("level") or "")
        score = verdict_data.get("score")
        if not score and level not in LEVEL_PILL:
            return "未检测"
        label = GRADE_LABELS.get(grade_of_verdict(verdict_data), LEVEL_PILL.get(level, ("", "未知"))[1])
        return f"{label} · {score} 分"

    @staticmethod
    def _subtitle(result: dict) -> str:
        """卡片头部的摘要行：接口·类型·容量·温度·寿命·通电时间。"""
        disk = result.get("disk") or {}
        counters = result.get("counters") or {}
        media = _media_text(str(disk.get("media_type") or ""), str(disk.get("bus_type") or ""))

        parts: list[str] = [f"{_bus_text(str(disk.get('bus_type') or ''))} · {media}"]
        parts.append(format_size(disk.get("size")))

        temp = counters.get("Temperature") if counters else None
        if isinstance(temp, int) and temp > 0:
            parts.append(f"{temp}°C")

        wear = counters.get("Wear") if counters else None
        if media == "SSD" and isinstance(wear, int) and wear >= 0:
            parts.append(f"寿命剩余 {max(0, 100 - wear)}%")

        hours_text = format_hours_pro(counters.get("PowerOnHours")) if counters else None
        if not hours_text:
            nvme = result.get("nvme_health") or {}
            hours_text = format_hours_pro(nvme.get("power_on_hours"))
        if hours_text:
            parts.append(hours_text)
        return "  ·  ".join(parts)

    # ------------------------------------------------------------------
    def _build_detail(self, result: dict) -> QWidget:
        """构建展开后的检测详情区。"""
        disk = result.get("disk") or {}
        verdict_data = result.get("verdict") or {}

        detail = QWidget()
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        def add_text(text: str, title: bool = False) -> QLabel:
            label = QLabel(text)
            label.setObjectName("detailTitle" if title else "detailText")
            label.setWordWrap(True)
            layout.addWidget(label)
            return label

        # 基本信息
        health_raw = str(disk.get("health_status") or "").lower()
        add_text(
            f"基本信息：序列号 {disk.get('serial') or '无'} · 接口 {_bus_text(str(disk.get('bus_type') or ''))} · "
            f"容量 {format_size(disk.get('size'))} · 系统状态 {HEALTH_TEXT.get(health_raw, health_raw or '未知')}"
        )

        # 专业指标（两列网格，取不到显示「—」）
        layout.addWidget(self._build_metrics_grid(result))

        # 事件日志（数量按等级着色：≥1 黄 / ≥8 橙 / ≥20 红）
        event_count = result.get("event_count") or 0
        event_recent = result.get("event_recent") or []
        event_level = metrics.level_for("event_count", event_count)
        if event_count > 0 or event_recent:
            event_label = add_text(
                f"事件日志：过去 30 天相关错误/警告 {event_count} 条",
                title=True,
            )
            if event_level >= metrics.LEVEL_CAUTION:
                event_label.setObjectName(f"metricValueL{event_level}")
                _repolish(event_label)
            for event in event_recent[:5]:
                add_text(f"· [{event.get('time')}] [{event.get('level_text')}] {event.get('provider')}：{event.get('message')}")
        else:
            add_text("事件日志：过去 30 天未发现与这块盘相关的错误/警告。")

        # 卷损坏位（提权状态下失败只说「无法读取」，不误导为权限问题）
        all_volumes = result.get("all_volumes") or []
        dirty_volumes = result.get("dirty_volumes") or []
        if all_volumes:
            if dirty_volumes:
                letters = "、".join(str(v.get("drive") or "?") for v in dirty_volumes)
                dirty_label = add_text(
                    f"卷损坏位：分区 {letters} 已置位「损坏位」，文件系统可能存在损坏。"
                )
                dirty_label.setObjectName("metricValueL3")
                _repolish(dirty_label)
            else:
                add_text("卷损坏位：该盘所有分区的损坏位标志均未置位。")

            # 剩余空间（v1.4：按阈值着色，低于 20% 开始提醒）
            for volume in all_volumes:
                pct = volume.get("free_pct")
                if not isinstance(pct, (int, float)):
                    continue
                free_gb = (volume.get("free") or 0) / 1024 ** 3
                total_gb = (volume.get("size") or 0) / 1024 ** 3
                level = metrics.level_for("free_space", pct)
                space_label = add_text(
                    f"剩余空间：{volume.get('drive')} 已用 {100 - pct:.0f}%"
                    f"（剩 {free_gb:.0f} GB / 共 {total_gb:.0f} GB）"
                )
                if level >= metrics.LEVEL_CAUTION:
                    space_label.setObjectName(f"metricValueL{level}")
                    _repolish(space_label)
        else:
            add_text(
                "卷损坏位：无法读取。"
                if self._admin
                else "卷损坏位：无法读取（需要管理员权限）。"
            )

        # SMART 属性表（SATA 盘）/ NVMe 健康数据明细（NVMe 盘）
        attrs = result.get("smart_attrs") or []
        nvme = result.get("nvme_health") or {}
        if attrs:
            add_text("SMART 属性明细", title=True)
            table = QTableWidget(len(attrs), 4, detail)
            table.setHorizontalHeaderLabels(["ID", "属性名称", "当前值", "原始值"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setStretchLastSection(True)
            table.setFixedHeight(min(230, 34 + len(attrs) * 26))
            for row, attr in enumerate(attrs):
                values = (str(attr.get("hex") or ""), str(attr.get("name") or ""), str(attr.get("value") or ""), str(attr.get("raw") or 0))
                is_bad = False
                try:
                    is_bad = int(attr.get("id") or 0) in _BAD_ATTR_IDS and int(attr.get("raw") or 0) > 0
                except (TypeError, ValueError):
                    is_bad = False
                for col, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    if is_bad:
                        item.setForeground(QColor("#C0392B"))
                    table.setItem(row, col, item)
            layout.addWidget(table)
        elif nvme:
            add_text("NVMe 健康数据", title=True)
            add_text(self._nvme_detail_text(nvme))
        else:
            add_text(
                "SMART 属性：此通道无法读取。"
                if self._admin
                else "SMART 属性：无法读取（权限不足或此通道不支持）。"
            )

        # 大白话建议
        add_text("建议", title=True)
        for reason in verdict_data.get("reasons", []):
            add_text("· " + reason)

        # 护盘小贴士（v1.5.1：按盘况轮换的专业养护建议）
        from core import care_tips

        disk_level = str(verdict_data.get("level") or "healthy")
        add_text("护盘小贴士", title=True)
        for tip in care_tips.tips_for_disk(disk_level, seed=self._tip_seed, count=3):
            add_text("· " + tip)

        return detail

    # ------------------------------------------------------------------
    @staticmethod
    def _nvme_detail_text(nvme: dict) -> str:
        """NVMe 健康数据明细（直读健康日志），取得到的字段才显示。"""
        lines: list[str] = []
        crit = nvme.get("critical_warning")
        if crit is not None:
            lines.append(f"危险警告：{'有（请立即备份）' if crit else '无'}")
        temp = nvme.get("temperature_c")
        if isinstance(temp, int) and temp > -100:
            lines.append(f"复合温度：{temp}°C")
        spare = nvme.get("available_spare_pct")
        if spare is not None:
            threshold = nvme.get("spare_threshold")
            threshold_text = f"（告警阈值 {threshold}%）" if threshold is not None else ""
            lines.append(f"可用备用空间：{spare}%{threshold_text}")
        pct = nvme.get("percentage_used")
        if pct is not None:
            lines.append(f"使用率（NVMe Percentage Used）：{pct}%")
        written = format_data_units(nvme.get("data_units_written"))
        if written:
            lines.append(f"累计写入量：{written}")
        read = format_data_units(nvme.get("data_units_read"))
        if read:
            lines.append(f"累计读取量：{read}")
        hours = nvme.get("power_on_hours")
        if hours is not None:
            hours_text = format_hours_pro(hours) or str(hours)
            lines.append(f"通电时间：{hours_text}")
        cycles = nvme.get("power_cycles")
        if cycles is not None:
            lines.append(f"通电次数：{format_int(cycles)}")
        unsafe = nvme.get("unsafe_shutdowns")
        if unsafe is not None:
            lines.append(f"不安全断电：{format_int(unsafe)} 次")
        media_errors = nvme.get("media_errors")
        if media_errors is not None:
            lines.append(f"媒体错误：{format_int(media_errors)} 个")
        err_entries = nvme.get("error_log_entries")
        if err_entries is not None:
            lines.append(f"错误日志条目：{format_int(err_entries)} 条")
        return "\n".join(lines) if lines else "健康日志已读取，但未返回有效字段。"

    @staticmethod
    def _smart_raw(attrs: list[dict], attr_id: int) -> int | None:
        """取指定 SMART 属性的原始值；缺失返回 None。（保留供外部调试使用）"""
        for attr in attrs:
            try:
                if int(attr.get("id") or 0) == attr_id:
                    return int(attr.get("raw") or 0)
            except (TypeError, ValueError):
                continue
        return None

    def _build_metrics_grid(self, result: dict) -> QFrame:
        """专业指标区（v1.3）：两列网格 + 数值四色警示 + 异常项忽略按钮。

        颜色语义：默认深色=正常信息；黄=注意；橙=警告；红=危险；
        被用户忽略的项显示健康绿 ✓（只影响显示，不影响评分）。
        """
        disk = result.get("disk") or {}
        serial = str(disk.get("serial") or "")
        store = get_store()
        items = metrics.metric_items_for_result(result)

        card = QFrame()
        card.setObjectName("metricsCard")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(3)

        cell_widgets: list[QWidget] = []
        for item in items:
            cell_widgets.append(self._make_metric_cell(serial, item, store))

        half = (len(cell_widgets) + 1) // 2
        for index, cell in enumerate(cell_widgets):
            row = index % half
            col_block = index // half
            base_col = col_block * 3
            grid.addWidget(cell, row, base_col, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(4, 1)
        return card

    def _make_metric_cell(self, serial: str, item: dict, store) -> QWidget:
        """单个指标单元格：label + 数值（按警示等级着色）+ 异常项忽略按钮。"""
        key = str(item.get("key") or "")
        level = int(item.get("level") or 0)
        text = str(item.get("text") or "—")
        ignore_key = store.ignore_key(serial, key)
        ignored = store.is_ignored(ignore_key)

        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label = QLabel(str(item.get("label") or ""))
        label.setObjectName("metricLabel")
        value = QLabel(("✓ " + text) if ignored else text)
        if ignored:
            value.setObjectName("metricValueIgnored")
            value.setToolTip("已忽略此警示，点击「恢复」可重新显示")
        else:
            value.setObjectName("metricValue" if level == metrics.LEVEL_OK else f"metricValueL{level}")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(label)
        row.addWidget(value, 1)

        if level >= metrics.LEVEL_CAUTION:
            btn = QPushButton("恢复" if ignored else "忽略")
            btn.setObjectName("ignoreBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("忽略后此项显示为健康绿色；评分不受影响，始终保持真实")
            btn.setFixedHeight(18)

            def _toggle(checked: bool = False, *, cell_key: str = ignore_key, cell_item: dict = item) -> None:
                now_ignored = not store.is_ignored(cell_key)
                store.set_ignored(cell_key, now_ignored)
                btn.setText("恢复" if now_ignored else "忽略")
                if now_ignored:
                    value.setText("✓ " + cell_item["text"])
                    value.setObjectName("metricValueIgnored")
                    value.setToolTip("已忽略此警示，点击「恢复」可重新显示")
                else:
                    value.setText(cell_item["text"])
                    lvl = int(cell_item.get("level") or 0)
                    value.setObjectName("metricValue" if lvl == metrics.LEVEL_OK else f"metricValueL{lvl}")
                    value.setToolTip("")
                _repolish(value)

            btn.clicked.connect(_toggle)
            row.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return cell

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        """点击卡片：立即展开 / 收起详情（v1.5.1 按反馈移除动画，秒开）。"""
        self._detail.setVisible(not self._detail.isVisible())
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """主窗口。"""

    def __init__(
        self,
        admin: bool = True,
        version: str = "v1.2",
        parent: QWidget | None = None,
        enable_tray: bool = False,
    ) -> None:
        """
        Args:
            admin: 是否管理员权限（界面提示用）。
            version: 版本号（标题栏 / 托盘 tooltip）。
            enable_tray: 是否启用托盘与开机自启动（真实 GUI 运行为 True；
                --smoke / offscreen 测试传 False，保证干净退出）。
        """
        super().__init__(parent)
        self._admin = admin
        self._results: list[dict] = []
        self._worker: DetectWorker | None = None
        self._progress_target = 0
        self._detect_started_at = 0.0
        self._tray = None            # TrayController | None（延迟导入构造）
        self._instance_server = None  # QLocalServer | None（单实例保护，main.py 注入）
        self._minimize_notified = False
        self._force_close = False
        self._detect_source = "手动体检"   # 本次检测来源（写入体检记录）
        self._boot_check_pending = False   # 开机静默体检等待空闲中
        self._boot_check_running = False   # 开机静默体检执行中（完成后弹气泡）
        self._detect_round = 0             # 检测轮次（护盘建议轮换种子）
        self._cards_by_device: dict[str, DiskCard] = {}  # v1.8：骨架卡片索引

        self.setWindowTitle(f"挖兔硬盘精灵 {version}")
        self.resize(860, 640)
        self.setMinimumSize(720, 560)
        self.setStyleSheet(QSS)
        self._apply_window_icon()
        self._build_ui(version)
        self._setup_tray_and_autostart(enable_tray, version)
        self._start_detection()

    # ------------------------------------------------------------------
    def _apply_window_icon(self) -> None:
        """窗口 / 应用图标（开发态 src/assets，打包态 _MEIPASS/assets）。"""
        path = app_icon_path()
        if path:
            self.setWindowIcon(QIcon(path))

    def _setup_tray_and_autostart(self, enable_tray: bool, version: str) -> None:
        """创建托盘控制器；首次真实运行默认开启开机启动（用户要求）。"""
        if not enable_tray:
            self._autostart_check.setChecked(False)
            return
        if QSystemTrayIcon.isSystemTrayAvailable():
            from ui.tray import TrayController

            self._tray = TrayController(self, version=version, parent=self)
        if not autostart.is_enabled():
            autostart.enable()
        else:
            # v1.5.1 兼容迁移：旧版快捷方式不带 --boot（开机会弹窗），补写一次
            autostart.ensure_boot_argument()
        # v1.0 定稿迁移：旧 DiskGuard.lnk 换成新名字快捷方式
        autostart.migrate_legacy_lnk()
        self._autostart_check.blockSignals(True)
        self._autostart_check.setChecked(autostart.is_enabled())
        self._autostart_check.blockSignals(False)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self, version: str) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ---- 顶部标题栏（v1.3：按用户要求移除右上角徽章） ----
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("挖兔硬盘精灵")
        title.setObjectName("title")
        ver_label = QLabel(version)
        ver_label.setObjectName("badgeGray")
        header.addWidget(title)
        header.addWidget(ver_label)
        header.addStretch()
        root.addLayout(header)

        # ---- 基础模式提示条 ----
        if not self._admin:
            tip = QLabel("当前未以管理员身份运行，SMART 属性、卷损坏位等检测项可能无法读取，结果仅供参考。建议右键「以管理员身份运行」。")
            tip.setObjectName("warnTip")
            tip.setWordWrap(True)
            root.addWidget(tip)

        # ---- 概览行：3 个指标卡 ----
        overview = QHBoxLayout()
        overview.setSpacing(10)
        self._ov_total = self._make_overview_card(overview, "ovCardGray", "ovNum", "0", "检测到硬盘（块）")
        self._ov_healthy = self._make_overview_card(overview, "ovCardGreen", "ovNumGreen", "0", "健康")
        self._ov_bad = self._make_overview_card(overview, "ovCardRed", "ovNumRed", "0", "警告 + 危险")
        root.addLayout(overview)

        # ---- 磁盘卡片列表（滚动区） ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        list_container = QWidget()
        self._list_layout = QVBoxLayout(list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch()
        self._scroll.setWidget(list_container)
        root.addWidget(self._scroll, 1)

        # ---- 体检记录面板（v1.3：健康痕迹，可折叠） ----
        self._history_panel = HistoryPanel()
        root.addWidget(self._history_panel)

        # ---- 底部：体检步骤清单 + 阶段文字 + 进度条 + 按钮 ----
        bottom = QVBoxLayout()
        bottom.setSpacing(6)

        self._steps = DetectStepsWidget()
        bottom.addWidget(self._steps)

        self._stage_label = QLabel("准备就绪")
        self._stage_label.setObjectName("stageLabel")
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.setRange(0, 100)
        self._progress.hide()
        self._progress_anim = QPropertyAnimation(self._progress, b"value", self)
        self._progress_anim.setDuration(900)
        self._progress_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        bottom.addWidget(self._stage_label)
        bottom.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._btn_detect = QPushButton("开始全盘检测")
        self._btn_detect.setObjectName("primary")
        self._btn_detect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_detect.clicked.connect(self._start_detection)
        self._btn_export = QPushButton("导出报告")
        self._btn_export.setObjectName("secondary")
        self._btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self._export_report)
        self._autostart_check = QCheckBox("开机自动启动")
        self._autostart_check.setObjectName("autostartCheck")
        self._autostart_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_check.toggled.connect(self._on_autostart_toggled)
        self._silent_check = QCheckBox("开机静默体检")
        self._silent_check.setObjectName("autostartCheck")
        self._silent_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._silent_check.setChecked(bool(get_store().get_setting("silent_boot_check", True)))
        self._silent_check.setToolTip("开机后等系统空闲，自动静默体检一次并记录；有问题才弹提醒")
        self._silent_check.toggled.connect(self._on_silent_toggled)
        note = QLabel("只读检测 · 不写入任何数据")
        note.setObjectName("note")
        btn_row.addWidget(self._btn_detect)
        btn_row.addWidget(self._btn_export)
        btn_row.addWidget(self._autostart_check)
        btn_row.addWidget(self._silent_check)
        self._github_btn = QPushButton("GitHub")
        self._github_btn.setObjectName("linkBtn")
        self._github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._github_btn.setToolTip("在 GitHub 上查看源码与版本更新")
        self._github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL))
        )
        btn_row.addWidget(self._github_btn)
        btn_row.addStretch()
        note.setToolTip("气泡提醒与提醒方案：请右键任务栏托盘图标 → 「提醒设置」")
        btn_row.addWidget(note, 0, Qt.AlignmentFlag.AlignBottom)
        bottom.addLayout(btn_row)

        root.addLayout(bottom)

    def _make_overview_card(self, parent_layout: QHBoxLayout, card_name: str, num_name: str, num_text: str, label_text: str) -> QLabel:
        """创建一个概览指标卡，返回数字标签以便后续更新。"""
        card = QFrame()
        card.setObjectName(card_name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        num = QLabel(num_text)
        num.setObjectName(num_name)
        label = QLabel(label_text)
        label.setObjectName("ovLabel")
        layout.addWidget(num)
        layout.addWidget(label)
        parent_layout.addWidget(card, 1)
        return num

    # ------------------------------------------------------------------
    # 检测流程
    # ------------------------------------------------------------------
    def is_detecting(self) -> bool:
        """是否正在前台检测（托盘后台检测前会查询）。"""
        return self._worker is not None and self._worker.isRunning()

    def start_detection_from_tray(self) -> None:
        """托盘菜单「立即检测」：唤起窗口并开始检测。"""
        self.wake_up()
        self._start_detection("手动体检")

    # ------------------------------------------------------------------
    # 开机静默体检（v1.3）：等系统空闲后自动体检一次，不弹窗口
    # ------------------------------------------------------------------
    def _on_silent_toggled(self, checked: bool) -> None:
        """「开机静默体检」开关：即时持久化（气泡提醒在托盘菜单设置）。"""
        get_store().set_setting("silent_boot_check", bool(checked))

    def maybe_start_boot_check(self) -> None:
        """开机静默体检入口（--boot 启动时由 main.py 调用）。

        首次等待 90 秒（避开开机 IO 高峰），之后每分钟看一眼系统是否
        空闲（用户闲置 ≥5 分钟或 CPU <25%）；最多等 10 分钟，到点即查。
        """
        if not bool(get_store().get_setting("silent_boot_check", True)):
            return  # 用户关闭了静默体检
        self._boot_check_pending = True
        self._boot_poll_count = 0
        QTimer.singleShot(90_000, self._poll_boot_check)

    def _poll_boot_check(self) -> None:
        from core import sysidle

        if not self._boot_check_pending:
            return
        self._boot_poll_count += 1
        if sysidle.system_is_idle() or self._boot_poll_count >= 10:
            self._boot_check_pending = False
            self._boot_check_running = True
            self._start_detection("开机体检")
        else:
            QTimer.singleShot(60_000, self._poll_boot_check)

    def _notify_boot_result(self, results: list) -> None:
        """开机体检完成后的托盘气泡：健康给安心，异常给提醒（v1.4 温度文案）。"""
        from core import tender

        if self._tray is None:
            return
        if not bool(get_store().get_setting("notify_enabled", True)):
            return
        if not results:
            self._tray.notify_custom(
                "开机体检未完成", "本次未能读取硬盘信息，可打开主界面手动检测。",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            return
        summary = verdict.summarize(results)
        bad = summary["warning"] + summary["danger"]
        greeting = tender.boot_greeting()
        if bad == 0:
            worst_space = None
            for result in results:
                for volume in result.get("all_volumes") or []:
                    pct = volume.get("free_pct")
                    if isinstance(pct, (int, float)) and (worst_space is None or pct < worst_space):
                        worst_space = pct
            if worst_space is not None and worst_space < 10:
                title, text = tender.pick("space_critical")
            elif worst_space is not None and worst_space < 20:
                title, text = tender.pick("space_low")
            else:
                title, text = tender.pick("ok")
            self._tray.notify_custom(f"{greeting}", f"{text}", QSystemTrayIcon.MessageIcon.Information)
        else:
            _, text = tender.pick("danger" if summary["danger"] else "warn")
            self._tray.notify_custom(
                "开机体检发现异常",
                f"{text}",
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def show_pending_boot_alert(self) -> None:
        """上次关机守护发现异常：开机后郑重提醒一次（读标记并清除）。"""
        store = get_store()
        alert = store.get_setting("pending_alert")
        if not alert:
            return
        store.set_setting("pending_alert", None)
        device = str((alert or {}).get("device") or "硬盘")
        reasons = "；".join((alert or {}).get("reasons") or [])
        text = f"{device}：{reasons}。建议立即备份重要数据。"
        if self._tray is not None:
            self._tray.notify_custom("上次关机前发现硬盘异常", text, QSystemTrayIcon.MessageIcon.Critical)
        get_store().append_history({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "level": "danger",
            "text": f"上次关机前检测到异常 —— {text}",
            "source": "关机守护",
        })
        if getattr(self, "_history_panel", None) is not None:
            self._history_panel.refresh()

    def _start_detection(self, source: str = "手动体检") -> None:
        """开始（或重新）全盘检测。source 记入体检记录。"""
        if self._worker is not None and self._worker.isRunning():
            return
        self._detect_source = source
        self._btn_detect.setEnabled(False)
        self._btn_detect.setText("检测中…")
        self._btn_export.setEnabled(False)
        self._detect_round += 1
        self._clear_cards()
        self._ov_total.setText("—")
        self._ov_healthy.setText("—")
        self._ov_bad.setText("—")
        self._stage_label.setText("正在体检…")
        self._progress.setValue(0)
        self._progress_target = 0
        self._progress.show()
        self._steps.reset()
        self._detect_started_at = time.perf_counter()

        self._worker = DetectWorker(self)
        self._worker.step_started.connect(self._on_step_started)
        self._worker.step_result.connect(self._on_step_result)
        self._worker.disks_enumerated.connect(self._show_skeleton_cards)
        self._worker.detect_finished.connect(self._on_detect_finished)
        self._worker.detect_failed.connect(self._on_detect_failed)
        self._worker.start()
        # 托盘图标「微微动」（v1.5）：体检期间低频轻旋
        if self._tray is not None:
            self._tray.start_activity()

    def _show_skeleton_cards(self, disks: list) -> None:
        """v1.8：枚举完成立即显示硬盘条目（骨架卡，评分稍后原地填充）。"""
        self._clear_cards()
        for index, disk in enumerate(disks or []):
            device_id = str(disk.get("device_id") or "")
            card = DiskCard(
                {"disk": disk, "verdict": {}}, admin=self._admin,
                tip_seed=self._detect_round, loading=True,
            )
            self._cards_by_device[device_id] = card
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)
            QTimer.singleShot(80 * index, lambda widget=card: _fade_in(widget))

    def _on_step_started(self, index: int) -> None:
        """步骤进入进行中：清单 spinner + 进度条平滑推进。"""
        self._steps.step_started(index)
        self._progress_target = min(92, 6 + index * 13)
        self._animate_progress(self._progress_target)

    def _on_step_result(self, index: int, ok: bool, summary: str) -> None:
        """步骤完成 / 失败：清单定格 + 进度条推进。"""
        self._steps.step_result(index, ok, summary)
        self._progress_target = min(92, 6 + (index + 1) * 13)
        self._animate_progress(self._progress_target)

    def _animate_progress(self, target: int) -> None:
        """把进度条平滑动画到目标值。"""
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self._progress.value())
        self._progress_anim.setEndValue(target)
        self._progress_anim.start()

    def _on_detect_finished(self, results: list) -> None:
        """检测完成：填充卡片（带渐入动画）、更新概览、同步托盘。"""
        self._results = results
        elapsed = time.perf_counter() - self._detect_started_at
        self._animate_progress(100)
        QTimer.singleShot(600, self._progress.hide)
        self._steps.finish(elapsed)
        self._stage_label.setText(f"检测完成 · 用时 {elapsed:.1f} 秒")
        self._populate_cards(results)

        summary = verdict.summarize(results)
        self._ov_total.setText(str(summary["total"]))
        self._ov_healthy.setText(str(summary["healthy"]))
        self._ov_bad.setText(str(summary["warning"] + summary["danger"]))

        self._btn_detect.setEnabled(True)
        self._btn_detect.setText("重新检测")
        self._btn_export.setEnabled(bool(results))

        self._record_history(results, True, elapsed)

        if self._tray is not None:
            self._tray.update_results(results)

        if self._boot_check_running:
            self._boot_check_running = False
            self._notify_boot_result(results)

        # v1.7：手动打开软件体检成功后也弹气泡（健康 5 秒；异常更久）
        if self._detect_source == "手动体检" and self._tray is not None and results:
            summary = verdict.summarize(results)
            from core import tender

            if summary["danger"]:
                _, text = tender.pick("danger")
                self._tray.notify_custom("体检报告", text, QSystemTrayIcon.MessageIcon.Critical)
            elif summary["warning"]:
                _, text = tender.pick("warn")
                self._tray.notify_custom("体检报告", text, QSystemTrayIcon.MessageIcon.Warning)
            else:
                _, text = tender.pick("ok")
                self._tray.notify_custom("体检报告", text, QSystemTrayIcon.MessageIcon.Information)

        if self._tray is not None:
            self._tray.stop_activity()

    def _record_history(self, results: list, ok: bool, elapsed: float, source: str | None = None) -> None:
        """把本次体检结果写入持久化体检记录并刷新面板（封顶 200 条）。

        Args:
            source: 覆盖本次来源（托盘定时体检会传「定时体检」）；
                None 则用 _start_detection 时设置的来源。
        """
        if source:
            self._detect_source = source
        if not ok:
            level, text = "warning", "体检未完成（部分检测项失败）"
        elif not results:
            level, text = "warning", "未读取到硬盘信息"
        else:
            summary = verdict.summarize(results)
            bad = summary["warning"] + summary["danger"]
            if summary["danger"]:
                level = "danger"
            elif summary["warning"]:
                level = "warning"
            else:
                level = "ok"
            text = (
                f"全部健康（{summary['total']} 块盘，{elapsed:.1f} 秒）"
                if level == "ok"
                else f"{bad} 块盘需要关注（共 {summary['total']} 块，{elapsed:.1f} 秒）"
            )
        detail_lines = self._history_detail_lines(results) if ok else []
        get_store().append_history({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "level": level,
            "text": text,
            "source": self._detect_source,
            "detail": detail_lines,
        })
        if getattr(self, "_history_panel", None) is not None:
            self._history_panel.refresh()

    @staticmethod
    def _history_detail_lines(results: list) -> list[str]:
        """体检记录的逐盘详情快照（点开记录时展示）。"""
        lines: list[str] = []
        for result in results or []:
            disk = result.get("disk") or {}
            verdict_data = result.get("verdict") or {}
            name = str(disk.get("model") or "未知硬盘")
            score = verdict_data.get("score")
            label = GRADE_LABELS.get(grade_of_verdict(verdict_data), "")
            bits = [f"{name} · {label}·{score} 分"]
            counters = result.get("counters") or {}
            nvme = result.get("nvme_health") or {}
            temp = counters.get("Temperature") if counters else None
            if not (isinstance(temp, int) and temp > 0):
                nvme_temp = nvme.get("temperature_c")
                if isinstance(nvme_temp, int) and nvme_temp > -100:
                    temp = nvme_temp
            if isinstance(temp, int) and temp > 0:
                bits.append(f"{temp}°C")
            wear = counters.get("Wear") if counters else None
            pct_used = nvme.get("percentage_used")
            if isinstance(wear, int) and 0 <= wear <= 100:
                bits.append(f"寿命 {max(0, 100 - wear)}%")
            elif isinstance(pct_used, int) and 0 <= pct_used <= 100:
                bits.append(f"寿命 {max(0, 100 - pct_used)}%")
            worst_space = None
            worst_volume = ""
            for volume in result.get("all_volumes") or []:
                pct = volume.get("free_pct")
                if isinstance(pct, (int, float)) and (worst_space is None or pct < worst_space):
                    worst_space = pct
                    worst_volume = str(volume.get("drive") or "")
            if worst_space is not None:
                bits.append(f"{worst_volume} 空间剩 {worst_space:.0f}%")
            lines.append(" · ".join(bits))
        return lines

    def _on_detect_failed(self, message: str) -> None:
        """检测失败提示（界面降级，不崩溃）。"""
        self._progress.hide()
        self._stage_label.setText("检测失败")
        self._btn_detect.setEnabled(True)
        self._btn_detect.setText("重新检测")
        for card in self._cards_by_device.values():
            card.apply_failed()
        self._record_history(self._results, False, time.perf_counter() - self._detect_started_at)
        if self._tray is not None:
            self._tray.stop_activity()
        QMessageBox.warning(self, "检测失败", f"检测过程中出现问题：{message}\n部分数据可能无法读取，请重试。")

    # ------------------------------------------------------------------
    # 卡片列表
    # ------------------------------------------------------------------
    def _clear_cards(self) -> None:
        """清空磁盘卡片列表（保留末尾的 stretch）。"""
        self._cards_by_device.clear()
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_cards(self, results: list[dict]) -> None:
        """检测结果落位（v1.8）：骨架卡原地填充；无骨架时才新建。"""
        if not results:
            if self._list_layout.count() <= 1:
                empty = QLabel("未读取到任何磁盘信息，请确认以管理员身份运行后重试。")
                empty.setObjectName("emptyTip")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._list_layout.insertWidget(0, empty)
                _fade_in(empty)
            return
        for index, result in enumerate(results):
            device_id = str((result.get("disk") or {}).get("device_id") or "")
            card = self._cards_by_device.get(device_id)
            if card is not None:
                card.apply_result(result)
            else:
                card = DiskCard(result, admin=self._admin, tip_seed=self._detect_round)
                self._cards_by_device[device_id] = card
                self._list_layout.insertWidget(self._list_layout.count() - 1, card)
                QTimer.singleShot(80 * index, lambda widget=card: _fade_in(widget))

    # ------------------------------------------------------------------
    # 开机启动（绿色方式：启动文件夹快捷方式）
    # ------------------------------------------------------------------
    def _on_autostart_toggled(self, checked: bool) -> None:
        """主界面 / 托盘任意一处开关：即时生效并同步另一处。"""
        ok = autostart.enable() if checked else autostart.disable()
        actual = autostart.is_enabled()
        if not ok or actual != checked:
            # 失败：回滚勾选状态并提示（容错，不崩溃）
            self._autostart_check.blockSignals(True)
            self._autostart_check.setChecked(actual)
            self._autostart_check.blockSignals(False)
            QMessageBox.warning(
                self,
                "开机启动设置失败",
                "无法写入启动文件夹快捷方式，请检查磁盘权限后重试。",
            )
        if self._tray is not None:
            self._tray.sync_autostart(actual)

    def set_autostart(self, enabled: bool) -> None:
        """供托盘菜单调用的开关入口（与主界面复选框共用逻辑）。"""
        if self._autostart_check.isChecked() != enabled:
            self._autostart_check.setChecked(enabled)
        else:
            self._on_autostart_toggled(enabled)

    # ------------------------------------------------------------------
    # 托盘：唤起 / 最小化到托盘 / 真正退出
    # ------------------------------------------------------------------
    def wake_up(self) -> None:
        """从托盘（或二次启动实例）唤起主窗口。"""
        notify_policy.mark_interacted()  # 习惯识别：用户互动 -> 静默计数清零
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def force_quit(self) -> None:
        """托盘菜单「退出」：真正退出进程（清理后台线程与托盘图标）。"""
        self._force_close = True
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        if self._tray is not None:
            self._tray.hide_tray()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    # ------------------------------------------------------------------
    # 导出报告
    # ------------------------------------------------------------------
    def _export_report(self) -> None:
        """用户选择路径后导出 HTML 报告（唯一会写磁盘的场景）。"""
        if not self._results:
            return
        default_name = f"硬盘健康报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path, _ = QFileDialog.getSaveFileName(self, "导出检测报告", default_name, "HTML 报告 (*.html)")
        if not path:
            return
        ok, error = report.export_report(path, self._results)
        if ok:
            QMessageBox.information(self, "导出成功", f"报告已保存到：\n{path}")
        else:
            QMessageBox.warning(self, "导出失败", f"报告写入失败：{error}")

    # ------------------------------------------------------------------
    def changeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        """最小化按钮 → 收进托盘（v1.7：任务栏不再保留最小化窗口）。"""
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            if self._tray is not None and not self._force_close:
                QTimer.singleShot(0, self.hide)
                if not self._minimize_notified:
                    self._minimize_notified = True
                    self._tray.notify_minimized()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        """关闭主窗口：有托盘时最小化到托盘（首次气泡提示），否则正常退出。"""
        if self._tray is not None and not self._force_close:
            event.ignore()
            self.hide()
            if not self._minimize_notified:
                self._minimize_notified = True
                self._tray.notify_minimized()
            return
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(event)
