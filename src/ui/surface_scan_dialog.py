# -*- coding: utf-8 -*-
"""盘面扫描对话框：选盘→ 选档位 → 后台扫描 → 盘面地图 + 结论。

设计要点（都来自实测，不是拍脑袋）：
- 必须能在扫描途中随时中止。坏道会让硬盘反复重试，一块卡住就是几十分钟，
  用户不能被锁死在这个窗口里，所以「停止」按钮随时可按。
- 全盘档要先把预计耗时摆出来再让用户点确认。实测本机 NVMe 全盘 4–8 分钟，
  机械盘按 80MB/s 算，1TB 要 3 小时以上——不提前说清楚会被当成卡死。
- 全程只读：不写盘、不标记坏簇、不调用 chkdsk，这点在界面上要说明白，
  免得用户以为扫完就等于「修复了」。
- 抽样档必须如实写明是抽样、可能漏掉局部坏道，不夸大结论。

盘面地图（20×20 格子热力图，v1.2）：
- 原来只有一个进度条，扫的时候干等，扫完只有一句话——太单调，也看不出
  坏块到底在盘的哪一段。现在把盘面按物理位置切成 400 格，扫到哪亮到哪。
- 颜色不只看「读没读出来」，还看「读得多慢」：坏道在彻底读不出来之前，
  往往先表现为明显变慢，这是提前预警，也是专业坏块工具的核心维度。
- 慢的判定用**相对基准**（本次扫描成功块的中位数），所以机械盘和 NVMe
  都能用同一套颜色；绝对毫秒会把两种盘的语义搞反。
- 两档共用同一套 400 格划分：快速档每格抽查 1 块，全盘档每格逐块读完。
  **快速档的绿只代表「这一格抽到的那一块读得快」，不等于整格都扫过**，
  界面必须写清楚抽查密度，这是防误导的底线。

v1.2 交互增强（本次）：
- 按钮合并：平时是「开始扫描 / 关闭」；一旦开始扫描，同一个主按钮变成
  「停止」，关闭按钮变成「隐藏」——隐藏后窗口收起但后台继续扫描，
  扫描完会自己弹回来并提醒（托盘气泡），不会悄悄丢结果。
- 多盘连扫：勾选多块硬盘后，扫完 A 自动接着扫 B（前提是你勾选了
  「扫描完成后自动接着扫描其他勾选的硬盘」）；不勾就一块一块手动点。
- 结果复用：每一次扫完的结果都会存到本机，导出报告时自动带上，
  不必为了出报告而重扫一遍。
- 非模态 + 主窗口联动（本次修复）：
  对话框改为非模态弹窗，隐藏后主窗口「盘面扫描」按钮实时显示
  「扫描中 12.33%」；扫描完成不弹硬窗，按钮变「扫描完成」，点击即可
  查看美化后的结果页。隐藏情况下扫完不强行弹窗，仅托盘提醒 + 按钮提示。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core import surface_scan
from core.surface_scan import (
    CELL_COLORS,
    CELL_FAILED,
    CELL_FAILED_RUN,
    CELL_LABELS,
    CELL_OK,
    CELL_PENDING,
    CELL_SLOW,
    CELL_VERY_SLOW,
    MODE_FULL,
    MODE_QUICK,
)

# 档位说明（扫描前就要让用户看清差别）
_MODE_ITEMS = (
    ("快速抽样（约 1 分钟，盘面 400 个区域各抽查 1 块）", MODE_QUICK),
    ("全盘逐块扫描（每个区域全部读完，机械盘可能数小时）", MODE_FULL),
)

# 图例顺序：从「好」到「坏」，最后才是「还没扫到」
_LEGEND_ORDER = (
    CELL_OK,
    CELL_SLOW,
    CELL_VERY_SLOW,
    CELL_FAILED,
    CELL_FAILED_RUN,
    CELL_PENDING,
)

# 结论等级 → 结果页左边条颜色（与界面健康分六档色一致）
_LEVEL_COLOR = {
    "good": "#10B981",
    "warn": "#F59E0B",
    "bad": "#EF4444",
}


class SurfaceGrid(QWidget):
    """20×20 盘面地图：一格 = 盘面的一段，扫到哪亮到哪。

    用 QWidget + paintEvent 手绘而不是摆 400 个 QLabel：400 个控件会让布局
    和刷新都变慢，而且每格只是个色块，手绘更轻也更可控。
    """

    CELL = 14  # 单格边长（px）
    GAP = 1    # 格间距（px）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._states = [CELL_PENDING] * surface_scan.GRID_CELLS
        side = self.CELL * surface_scan.GRID_COLS + self.GAP * (surface_scan.GRID_COLS - 1)
        self.setFixedSize(side, side)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def reset(self) -> None:
        """全部恢复成「未扫描」的灰色。"""
        self._states = [CELL_PENDING] * surface_scan.GRID_CELLS
        self.update()

    def set_state(self, index: object, state: object) -> None:
        """点亮单格（扫描途中逐格刷新用）。"""
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return
        if 0 <= idx < len(self._states):
            try:
                self._states[idx] = int(state)
            except (TypeError, ValueError):
                return
            self.update()

    def set_all(self, states: object) -> None:
        """整体重绘（扫描结束后用最终颜色覆盖途中的暂定色）。"""
        if not isinstance(states, (list, tuple)):
            return
        for idx, state in enumerate(states):
            if idx >= len(self._states):
                break
            try:
                self._states[idx] = int(state)
            except (TypeError, ValueError):
                self._states[idx] = CELL_PENDING
        self.update()

    def states(self) -> list[int]:
        return list(self._states)

    def scanned_count(self) -> int:
        """已经扫过（不再是灰色）的格子数。"""
        return sum(1 for s in self._states if s != CELL_PENDING)

    def paintEvent(self, event) -> None:  # noqa: N802 （Qt 的命名约定）
        painter = QPainter(self)
        step = self.CELL + self.GAP
        for idx, state in enumerate(self._states):
            col = idx % surface_scan.GRID_COLS
            row = idx // surface_scan.GRID_COLS
            painter.fillRect(
                col * step, row * step, self.CELL, self.CELL,
                QColor(surface_scan.cell_color(state)),
            )
        painter.end()


class SurfaceScanThread(QThread):
    """后台扫描线程：把 core.surface_scan 的回调转成 Qt 信号。"""

    # 进度用 object而非 int：Qt 的 int 是32 位有符号（上限 2147483647），
    # 而 2GB = 2147483648 已经越界，全盘档 1TB 会溢出 500 倍——必须避开 int。
    progress = Signal(object, object, int)  # 已读字节, 计划字节, 失败块数
    cell_changed = Signal(int, int)  # 格子编号, 格子状态（都在 400 以内，int 安全）
    finished_ok = Signal(dict)

    def __init__(self, device_id: str, total_bytes: int, mode: str, parent=None) -> None:
        super().__init__(parent)
        self._device_id = device_id
        self._total_bytes = int(total_bytes or 0)
        self._mode = mode
        self._aborted = False
        self._cell_seen: dict[int, int] = {}

    def abort(self) -> None:
        self._aborted = True

    def _is_aborted(self) -> bool:
        return self._aborted

    def run(self) -> None:
        try:
            result = surface_scan.scan_surface(
                self._device_id,
                self._total_bytes,
                mode=self._mode,
                progress=self._on_progress,
                is_aborted=self._is_aborted,
                on_cell=self._on_cell,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # 兜底：不让后台异常把整个应用带崩
            self.finished_ok.emit(
                {"error": str(exc) or f"扫描失败：{type(exc).__name__}", "finished": False}
            )

    def _on_progress(self, done: int, planned: int, bad: int) -> bool:
        self.progress.emit(int(done), int(planned), int(bad))
        return not self._aborted

    def _on_cell(self, index: int, state: int) -> None:
        """逐格点亮。全盘档有几十万块，只在颜色真的变了才发信号——
        否则几十万次跨线程信号会把界面事件队列冲垮。"""
        idx = int(index)
        value = int(state)
        if self._cell_seen.get(idx) == value:
            return
        self._cell_seen[idx] = value
        self.cell_changed.emit(idx, value)


class SurfaceScanDialog(QDialog):
    """盘面扫描对话框：负责选盘、选档、跑扫描、显示盘面地图与结论。

    tray: 可选，主窗口的托盘控制器。隐藏扫描完成后用它弹气泡提醒。

    信号（给主窗口联动用）：
    - scan_progress(percent: float)：扫描进度百分比（0~100，保留两位小数展示）。
    - scan_state_changed(state: str)：整体会话状态，取值
      "scanning" / "finished" / "paused" / "idle" / "hidden" / "shown"。
    """

    scan_progress = Signal(object)
    scan_state_changed = Signal(str)

    def __init__(self, disks: list[dict], parent=None, tray=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("盘面扫描（坏道扫描）")
        self.setMinimumWidth(540)
        self._disks = [d for d in disks if str((d or {}).get("device_id") or "").isdigit()]
        self._tray = tray
        self._thread: SurfaceScanThread | None = None
        self._result: dict = {}
        self._speed_mb_s = 0.0

        # ---- 扫描状态机 ----
        self._scanning = False       # 是否正在扫描中（决定按钮文案与行为）
        self._paused = False         # 多盘手动连扫：上一步扫完、等待用户点「继续」
        self._closing = False        # _finish 主动关闭时置位，区分「用户点 X」
        self._was_hidden = False     # 扫描途中是否被「隐藏」（结束后要弹回来）
        self._auto_chain = False     # 多盘是否自动连扫
        self._queue: list[str] = []  # 待扫设备编号队列（按界面勾选顺序）
        self._total_in_chain = 0     # 本次勾选的盘总数（用于「第 n/m 块」）
        self._done_in_chain = 0      # 已经开扫的盘数
        self._current_device_id = ""  # 当前正在/即将扫描的盘
        self._current_disk: dict = {}

        root = QVBoxLayout(self)
        root.setSpacing(10)

        intro = QLabel(
            "逐块读取硬盘表面，检查有没有读不出来的地方——"
            "这类故障常常还没被 SMART 记上，能补上「检测全绿但盘实际不稳」这个盲区。\n"
            "全程只读：不写入、不标记坏簇、不修复任何东西。"
        )
        intro.setObjectName("note")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # 选盘：改成可多选的勾选列表（支持多盘连扫）。默认勾上第一块。
        self._disk_list, self._disk_items = self._build_disk_list()
        root.addWidget(self._make_row("勾选要扫描的硬盘（可多选）：", self._disk_list))

        self._mode_box = self._build_mode_box()
        root.addWidget(self._make_row("扫描范围：", self._mode_box))

        # 多盘连扫开关：默认关，勾上才自动 A→B→C
        self._chain_cb = QCheckBox("扫描完成后自动接着扫描其他勾选的硬盘")
        self._chain_cb.setObjectName("note")
        self._chain_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self._chain_cb)

        self._estimate = QLabel("")
        self._estimate.setObjectName("note")
        self._estimate.setWordWrap(True)
        root.addWidget(self._estimate)

        # ---- 盘面地图：20×20 格子，扫到哪亮到哪 ----
        self._grid = SurfaceGrid()
        grid_card = QFrame()
        grid_card.setObjectName("gridCard")
        grid_wrap = QVBoxLayout(grid_card)
        grid_wrap.setContentsMargins(10, 10, 10, 8)
        grid_wrap.setSpacing(6)
        grid_head = QHBoxLayout()
        grid_head.setContentsMargins(0, 0, 0, 0)
        grid_head.setSpacing(6)
        map_title = QLabel("盘面地图（每格 = 盘面的一段，从上到下依次为盘的开头到末尾）")
        map_title.setObjectName("note")
        self._grid_count = QLabel("已扫 0 / 400 格")
        self._grid_count.setObjectName("note")
        grid_head.addWidget(map_title)
        grid_head.addStretch()
        grid_head.addWidget(self._grid_count)
        grid_wrap.addLayout(grid_head)

        grid_line = QHBoxLayout()
        grid_line.setContentsMargins(0, 0, 0, 0)
        grid_line.addStretch()
        grid_line.addWidget(self._grid)
        grid_line.addStretch()
        grid_wrap.addLayout(grid_line)

        grid_wrap.addWidget(self._build_legend())
        self._density = QLabel("")
        self._density.setObjectName("note")
        self._density.setWordWrap(True)
        grid_wrap.addWidget(self._density)
        root.addWidget(grid_card)

        # ---- 扫描信息区：固定高度容器，避免进度条出现/消失导致整体布局抖动 ----
        # 修复「扫描过程中区域变形、下方文字上移挡住」的根因：把进度条+状态
        # 放进一个固定高度的区域，无论进度条是否显示，整体布局高度都不变。
        self._scan_area = QWidget()
        self._scan_area.setFixedHeight(60)
        scan_area_layout = QVBoxLayout(self._scan_area)
        scan_area_layout.setContentsMargins(0, 0, 0, 0)
        scan_area_layout.setSpacing(6)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(True)
        self._bar.setFixedHeight(18)
        self._bar.hide()
        self._status = QLabel("准备就绪")
        self._status.setObjectName("stageLabel")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(34)
        scan_area_layout.addWidget(self._bar)
        scan_area_layout.addWidget(self._status)
        root.addWidget(self._scan_area)

        # ---- 美化后的结果页（非硬弹窗）：扫完在对话框内展示，隐藏时点击按钮再唤出 ----
        self._result_panel = self._build_result_panel()
        self._result_panel.hide()
        root.addWidget(self._result_panel)

        # ---- 按钮：平时「开始扫描 / 关闭」，扫描中「停止 / 隐藏」 ----
        buttons = QHBoxLayout()
        buttons.addStretch()
        self._go_btn = QPushButton("开始扫描")
        self._go_btn.setObjectName("primary")
        self._go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._go_btn.clicked.connect(self._on_go)
        self._sec_btn = QPushButton("关闭")
        self._sec_btn.setObjectName("secondary")
        self._sec_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sec_btn.clicked.connect(self._on_secondary)
        buttons.addWidget(self._go_btn)
        buttons.addWidget(self._sec_btn)
        root.addLayout(buttons)

        self._update_estimate()

    # ---------------------------------------------------------------- 构建

    @staticmethod
    def _make_row(label_text: str, widget: QWidget) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(label_text)
        label.setObjectName("note")
        row.addWidget(label)
        row.addWidget(widget, 1)
        return holder

    def _build_disk_list(self) -> tuple[QListWidget, list[QListWidgetItem]]:
        """可多选的勾选列表：每项 = 一块盘，数据里藏 device_id。"""
        box = QListWidget()
        box.setMinimumHeight(96)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        items: list[QListWidgetItem] = []
        for disk in self._disks:
            name = str(disk.get("model") or "未知型号").strip()
            size = surface_scan.format_size(disk.get("size"))
            item = QListWidgetItem(f"{name}（{size}）")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, str(disk.get("device_id")))
            box.addItem(item)
            items.append(item)
        if items:
            # 默认勾上第一块即可；其余保留勾选状态供用户按需增删
            items[0].setCheckState(Qt.CheckState.Checked)
        box.itemChanged.connect(lambda *_: self._update_estimate())
        return box, items

    def _build_mode_box(self) -> QComboBox:
        box = QComboBox()
        for text, mode in _MODE_ITEMS:
            box.addItem(text, mode)
        box.currentIndexChanged.connect(self._update_estimate)
        return box

    def _build_legend(self) -> QWidget:
        """六色图例：颜色沿用主界面健康分的六档色，口径一致不用重新记。"""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._legend_labels: dict[int, QLabel] = {}
        for state in _LEGEND_ORDER:
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background:{CELL_COLORS[state]}; border-radius:2px;"
            )
            text = QLabel(f"{CELL_LABELS[state]} 0")
            text.setObjectName("note")
            row.addWidget(swatch)
            row.addWidget(text)
            self._legend_labels[state] = text
        row.addStretch()
        return holder

    def _build_result_panel(self) -> QFrame:
        """扫完后的美化结果页（替代硬弹窗 QMessageBox）。"""
        card = QFrame()
        card.setObjectName("resultCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        self._result_title = QLabel("")
        self._result_title.setObjectName("resultTitle")
        self._result_body = QLabel("")
        self._result_body.setObjectName("note")
        self._result_body.setWordWrap(True)
        self._result_note = QLabel(
            "结果已保存到本机，导出报告时会自动包含本次盘面扫描，无需重新扫描。"
        )
        self._result_note.setObjectName("note")
        self._result_note.setWordWrap(True)
        layout.addWidget(self._result_title)
        layout.addWidget(self._result_body)
        layout.addWidget(self._result_note)
        return card

    def _update_grid_info(self) -> None:
        """刷新「已扫 N/400 格」与图例各色数量。"""
        states = self._grid.states()
        counts = surface_scan.cell_counts(states)
        self._grid_count.setText(f"已扫 {self._grid.scanned_count()} / {surface_scan.GRID_CELLS} 格")
        for state, label in self._legend_labels.items():
            label.setText(f"{CELL_LABELS[state]} {counts.get(state, 0)}")

    # ---------------------------------------------------------------- 选盘辅助

    def _disk_by_id(self, device_id: str) -> dict:
        for disk in self._disks:
            if str(disk.get("device_id")) == str(device_id):
                return disk
        return {}

    def _selected_disk(self) -> dict:
        """当前要扫的盘：优先正在扫的那块，否则回到界面上第一个勾选的。"""
        if self._current_device_id:
            d = self._disk_by_id(self._current_device_id)
            if d:
                return d
        for item in self._disk_items:
            if item.checkState() == Qt.CheckState.Checked:
                d = self._disk_by_id(item.data(Qt.ItemDataRole.UserRole))
                if d:
                    return d
        return {}

    def _selected_mode(self) -> str:
        return str(self._mode_box.currentData() or MODE_QUICK)

    def _build_queue_from_selection(self) -> list[str]:
        """按界面勾选顺序收集待扫盘的设备编号。"""
        queue: list[str] = []
        for item in self._disk_items:
            if item.checkState() == Qt.CheckState.Checked:
                device_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
                if device_id and device_id not in queue:
                    queue.append(device_id)
        return queue

    # ---------------------------------------------------------------- 估算文案

    def _update_estimate(self) -> None:
        """切换盘/档位时刷新耗时预估。

        只在已测过速度后才有可信估算；没测过就如实说「首次扫描后才给预估」，
        不编一个数字出来骗用户。
        """
        disk = self._selected_disk()
        mode = self._selected_mode()
        size = surface_scan.format_size(disk.get("size"))
        if mode == MODE_QUICK:
            # 抽查密度必须写清楚：热力图上刷满 400 格很容易被理解成「整盘都扫过」，
            # 而实际上每格只读了 1 块——不说明白就是误导。
            self._density.setText(
                "抽查密度：盘面 400 个区域，每个区域抽查 1 块（共约 1.6GB）。"
                "格子变绿只代表「这一格抽到的那一块读得快」，不等于整格都扫过；"
                "要确认整段请跑全盘扫描。抽样可能漏掉局部的坏道。"
            )
            self._estimate.setText(
                f"快速抽样会把盘面切成 400 个区域、每区抽查 1 块，共约 1.6GB（本盘 {size}），"
                "通常 1 分钟内完成。"
                "注意：抽样可能漏掉局部的坏道，结论会如实标注为「抽样」。"
            )
            return
        self._density.setText(
            "抽查密度：盘面 400 个区域全部逐块读完，格子颜色代表这一整段的整体情况。"
        )
        estimate = ""
        if self._speed_mb_s > 0:
            estimate = surface_scan.estimate_full_scan_time(disk.get("size"), self._speed_mb_s)
        tail = f"预计 {estimate}。" if estimate else "耗时取决于读写速度，首次扫描后才能给出预估。"
        self._estimate.setText(
            f"全盘逐块扫描会读完整个 {size}，{tail}"
            "机械硬盘可能要几个小时，扫描期间电脑仍可正常使用。"
        )

    # ---------------------------------------------------------------- 状态机

    def _enter_scanning(self) -> None:
        """进入「扫描中」：主按钮变「停止」，次按钮变「隐藏」，锁定选择。"""
        self._scanning = True
        self._paused = False
        self._result_panel.hide()
        self._disk_list.setEnabled(False)
        self._mode_box.setEnabled(False)
        self._chain_cb.setEnabled(False)
        self._go_btn.setText("停止")
        self._go_btn.setEnabled(True)
        self._sec_btn.setText("隐藏")
        self._sec_btn.setEnabled(True)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.show()
        self._grid.reset()
        self._update_grid_info()
        self.scan_state_changed.emit("scanning")
        self.scan_progress.emit(0.0)

    def _enter_idle(self, go_text: str = "开始扫描", paused: bool = False) -> None:
        """回到空闲：主按钮变可再次发起扫描，次按钮变「关闭」，恢复选择。

        注意：这里不直接发状态信号，由调用方按需发 "idle" / "paused" / "finished"，
        避免与主窗口「盘面扫描」按钮的语义冲突。
        """
        self._scanning = False
        self._paused = paused
        self._disk_list.setEnabled(True)
        self._mode_box.setEnabled(True)
        self._chain_cb.setEnabled(True)
        self._go_btn.setText(go_text)
        self._go_btn.setEnabled(True)
        self._sec_btn.setText("关闭")
        self._sec_btn.setEnabled(True)
        self._bar.hide()

    def _on_go(self) -> None:
        """主按钮：扫描中=停止；手动连扫暂停中=继续下一台；空闲=开始扫描。"""
        if self._scanning:
            self._on_stop()
        elif self._paused:
            self._start_next()
        else:
            self._on_start()

    def _on_secondary(self) -> None:
        """次按钮：扫描中=隐藏（后台继续）；空闲=关闭对话框。"""
        if self._scanning:
            self._hide_during_scan()
        else:
            self._finish()

    def _hide_during_scan(self) -> None:
        """扫描途中收起窗口但继续后台扫描；扫完会自动弹回来并提醒。"""
        self._was_hidden = True
        self.hide()
        self.scan_state_changed.emit("hidden")

    # ---------------------------------------------------------------- 扫描流程

    def _on_start(self) -> None:
        # 注：原「全盘扫描二次确认弹窗」已移除——用户要求勾选后自动扫、不要
        # 弹窗再确认。耗时风险已在上方估算文案中写清，按钮点击即视为同意。
        queue = self._build_queue_from_selection()
        if not queue:
            QMessageBox.warning(self, "请先勾选", "请至少勾选一块要扫描的硬盘。")
            return

        self._queue = list(queue)
        self._auto_chain = self._chain_cb.isChecked()
        self._total_in_chain = len(self._queue)
        self._done_in_chain = 0
        self._start_next()

    def _start_next(self) -> None:
        """从队列里取下一个盘开扫；队列空了就收尾。"""
        if not self._queue:
            self._enter_idle("重新扫描")
            self._status.setText(
                f"全部所选硬盘（{self._total_in_chain} 块）扫描完成，"
                "结果已保存到本机，导出报告时会自动包含，无需重新扫描。"
            )
            self.scan_state_changed.emit("finished")
            return

        self._current_device_id = self._queue.pop(0)
        self._current_disk = self._disk_by_id(self._current_device_id)
        self._done_in_chain += 1
        disk = self._current_disk
        device_id = str(disk.get("device_id") or "")
        mode = self._selected_mode()
        if not device_id:
            # 极端情况下盘信息缺失，跳过这块继续下一台
            self._start_next()
            return

        self._enter_scanning()
        chain_text = f"（第 {self._done_in_chain}/{self._total_in_chain} 块）" \
            if self._total_in_chain > 1 else ""
        self._status.setText(f"扫描中{chain_text}：{disk.get('model') or '未知型号'}，只读读取中，请勿关机…")

        self._thread = SurfaceScanThread(device_id, int(disk.get("size") or 0), mode, parent=self)
        self._thread.progress.connect(self._on_progress)
        self._thread.cell_changed.connect(self._on_cell_changed)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.start()

    def _on_stop(self) -> None:
        if self._thread is not None:
            self._thread.abort()
            self._go_btn.setEnabled(False)
            self._status.setText("正在停止…")

    def _on_progress(self, done: object, planned: object, bad: int) -> None:
        done = int(done or 0)
        planned = int(planned or 0)
        percent = (done * 100.0 / planned) if planned > 0 else 0.0
        self._bar.setValue(min(int(percent), 100))
        read_text = surface_scan.format_size(done)
        if bad > 0:
            self._status.setText(f"扫描中 {percent:.2f}%（已读 {read_text}，发现 {bad} 块读失败）")
        else:
            self._status.setText(f"扫描中 {percent:.2f}%（已读 {read_text}）")
        # 回传主窗口按钮「扫描中 12.33%」实时显示
        self.scan_progress.emit(percent)

    def _on_cell_changed(self, index: int, state: int) -> None:
        """扫一块亮一格：让等待过程看得见进展，而不是干等进度条。"""
        self._grid.set_state(index, state)
        self._update_grid_info()

    def _on_finished(self, result: dict) -> None:
        # 异常（打不开盘等）：回空闲并提示，不存结果
        if result.get("error") and not result.get("finished"):
            self._enter_idle("重新扫描")
            self._status.setText("扫描未开始")
            self.scan_state_changed.emit("idle")
            QMessageBox.warning(self, "无法扫描", str(result.get("error")))
            return
        # 用户主动中止：绝不当作「无故障」结论，直接回空闲
        if result.get("cancelled") or not result.get("finished"):
            self._enter_idle("重新扫描")
            self._status.setText("已停止扫描（中途停止的结果不作结论，需重扫整盘才能判定）")
            self.scan_state_changed.emit("idle")
            return

        # ---- 成功扫完一块 ----
        self._result = result
        # 途中那版颜色是暂定的（还算不出「慢」的基准），这里用最终颜色整体重绘
        cells = result.get("cells") or surface_scan.decode_cells(result.get("cells_code"))
        if cells:
            self._grid.set_all(cells)
        self._update_grid_info()

        if result.get("speed_mb_s"):
            self._speed_mb_s = float(result["speed_mb_s"])
            self._update_estimate()

        # v1.2：存下最近一次结果，导出报告时要展示（中止的不存）
        self._persist_result(result)

        level, message = surface_scan.interpret(result)

        # 美化结果页：在对话框内展示，不弹硬窗
        self._show_result_panel(level, message, result)

        chain_text = f"（第 {self._done_in_chain}/{self._total_in_chain} 块）" \
            if self._total_in_chain > 1 else ""

        # 隐藏情况下：不强行弹窗；用托盘气泡提醒 + 主按钮「扫描完成」
        if self._was_hidden:
            self._was_hidden = False
            if self._tray is not None and not self._queue:
                model = str(self._current_disk.get("model") or "硬盘")
                self._tray.notify_custom(
                    "盘面扫描完成",
                    f"「{model}」{chain_text}扫描完成，结果已保存。点击主界面「盘面扫描」按钮查看详情。",
                    QSystemTrayIcon.MessageIcon.Information,
                )
        else:
            # 未隐藏：对话框就在眼前，直接展示结果页 + 轻量托盘提醒
            if self._tray is not None:
                model = str(self._current_disk.get("model") or "硬盘")
                self._tray.notify_custom(
                    "盘面扫描完成",
                    f"「{model}」{chain_text}扫描完成，结果已保存。",
                    QSystemTrayIcon.MessageIcon.Information,
                )

        self._after_result_dialog(chain_text)

    def _after_result_dialog(self, chain_text: str = "") -> None:
        """一块的结果展示完：还有盘要扫就继续，否则收尾。"""
        if self._queue:
            if self._auto_chain:
                self._start_next()  # 自动连扫：继续下一台（会再次进入 scanning）
            else:
                # 手动连扫：停在这里等用户点「继续扫描（第 n/m 块）」
                self._enter_idle(
                    go_text=f"继续扫描（第 {self._done_in_chain + 1}/{self._total_in_chain} 块）",
                    paused=True,
                )
                self._status.setText(
                    f"第 {self._done_in_chain}/{self._total_in_chain} 块已完成，"
                    "结果已保存。点击「继续扫描」处理下一块勾选的硬盘；"
                    "或勾选「自动接着扫描」让它一口气扫完。"
                )
                self.scan_state_changed.emit("paused")
            return
        self._enter_idle("重新扫描")
        self._status.setText(
            f"全部所选硬盘（{self._total_in_chain} 块）扫描完成，"
            "结果已保存到本机，导出报告时会自动包含，无需重新扫描。"
        )
        self.scan_state_changed.emit("finished")

    def _persist_result(self, result: dict) -> None:
        """把扫描结果存进本地设置，供导出报告展示「最近一次盘面扫描」。

        只存真跑完的；中止的不存——否则报告里会出现一条「未发现读失败区域」
        的半截结论，那是最容易误导人的一种记录。
        """
        if not result or not result.get("finished") or result.get("cancelled"):
            return
        try:
            from core.store import get_store

            get_store().save_surface_scan(str(result.get("device_id") or ""), {
                "model": self._current_disk.get("model") or "",
                "mode": result.get("mode"),
                "chunks_ok": int(result.get("chunks_ok") or 0),
                "chunks_failed": int(result.get("chunks_failed") or 0),
                "bytes_scanned": int(result.get("bytes_scanned") or 0),
                "elapsed_sec": round(float(result.get("elapsed_sec") or 0), 2),
                "speed_mb_s": round(float(result.get("speed_mb_s") or 0), 1),
                # 盘面地图：400 格压成一个字符串存，导出报告时原样画出来
                "cells_code": surface_scan.encode_cells(result.get("cells")),
                "cells_scanned": int(result.get("cells_scanned") or 0),
                "slow_cells": int(result.get("slow_cells") or 0),
                "very_slow_cells": int(result.get("very_slow_cells") or 0),
                "bad_cells": int(result.get("bad_cells") or 0),
                "baseline_ms": round(float(result.get("baseline_ms") or 0), 3),
            })
        except Exception:  # 存不下去也不能影响扫描结论的展示
            pass

    def _show_result_panel(self, level: str, message: str, result: dict) -> None:
        """把结果渲染进美化结果页（替代硬弹窗 QMessageBox）。"""
        chain_text = f"（第 {self._done_in_chain}/{self._total_in_chain} 块）" \
            if self._total_in_chain > 1 else ""
        color = _LEVEL_COLOR.get(level, _LEVEL_COLOR["good"])
        title = f"盘面扫描完成 {chain_text}".strip()
        self._result_title.setText(title)

        lines = [message]
        if result.get("finished"):
            lines.append(
                f"读取 {surface_scan.format_size(result.get('bytes_scanned'))}，"
                f"用时 {float(result.get('elapsed_sec') or 0):.1f} 秒，"
                f"速度 {float(result.get('speed_mb_s') or 0):.0f} MB/s"
            )
            lines.append(self._grid_summary_line(result))
        if result.get("mode") == MODE_QUICK and result.get("finished"):
            lines.append("提示：这是抽样结果。若怀疑硬盘有间歇性故障，可再跑一次全盘扫描确认。")
        if level == "bad":
            lines.append("建议：先备份重要数据，再考虑更换硬盘。")
        self._result_body.setText("\n".join(lines))

        self._result_panel.setStyleSheet(
            "QFrame#resultCard{background:#F8FAFC;border:1px solid #E2E8F0;"
            f"border-left:4px solid {color};border-radius:10px;}}"
            "QLabel#resultTitle{font-weight:600;font-size:14px;color:#0F172A;}"
        )
        self._result_panel.show()

    @staticmethod
    def _grid_summary_line(result: dict) -> str:
        """盘面地图的一句话总结——把图上的信息也说给不方便看图的人听。"""
        scanned = int(result.get("cells_scanned") or 0)
        bad_cells = int(result.get("bad_cells") or 0)
        slow_cells = int(result.get("slow_cells") or 0)
        parts = [f"盘面 {scanned}/{surface_scan.GRID_CELLS} 个区域已读"]
        if bad_cells:
            parts.append(f"{bad_cells} 个区域读失败")
        if slow_cells:
            parts.append(f"{slow_cells} 个区域读取明显偏慢")
        if not bad_cells and not slow_cells:
            parts.append("未发现读失败或明显偏慢的区域")
        return "；".join(parts)

    def closeEvent(self, event) -> None:  # noqa: N802 （Qt 命名约定）
        """扫描途中用户按 X / Esc：不要直接关掉（会杀掉正在跑的后台扫描），
        改成「隐藏后台继续」——和「隐藏」按钮一个意思，可随时从主界面唤回。"""
        if self._scanning and not self._closing:
            event.ignore()
            self._hide_during_scan()
            return
        super().closeEvent(event)
        # 对话框真正关闭（空闲态按 X / 关闭按钮）→ 通知主窗口复位按钮
        self.scan_state_changed.emit("idle")

    def _finish(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.abort()
            self._thread.wait(3000)
        self._closing = True
        self.scan_state_changed.emit("idle")
        self.accept()
