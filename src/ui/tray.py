# -*- coding: utf-8 -*-
"""系统托盘：常驻图标随健康档位变色 + 后台定时检测 + 单实例保护。

职责：
- QSystemTrayIcon 常驻托盘：图标用 QPainter 程序化绘制（圆角方形底取当前
  档位颜色 + 白色简笔硬盘 + 危险档角标白色感叹号），共 6+1 张 QIcon 缓存；
- 托盘菜单：打开主界面 / 立即检测 / 开机启动（可勾选）/ 退出（真正退出进程）；
- 单击托盘图标打开 / 唤起主窗口；
- 后台静默检测：QTimer 每 2 小时复用 DetectWorker 跑一次完整检测，
  只更新托盘图标与 tooltip，不弹窗；仅当等级比上次更差时气泡通知一次；
- 单实例保护：QLocalServer/QLocalSocket（命名管道），二次启动唤起已有实例。

绿色版约束：不写注册表、不联网、不留临时文件（QLocalServer 仅系统命名管道）。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from core import autostart
from core.verdict import (
    GRADE_COLORS,
    GRADE_CRITICAL,
    GRADE_DANGEROUS,
    GRADE_LABELS,
    GRADE_UNKNOWN,
    grade_of_verdict,
)

# 单实例命名管道标识（与版本无关，保证跨小版本互相识别）
INSTANCE_KEY = "WatuDiskSprite-LocalInstance"

# 后台静默检测周期：2 小时
BACKGROUND_INTERVAL_MS = 2 * 60 * 60 * 1000


# ----------------------------------------------------------------------
# 单实例保护
# ----------------------------------------------------------------------
def is_already_running() -> bool:
    """探测是否已有 DiskGuard 实例在运行（能连上命名管道即视为已运行）。"""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_KEY)
    running = socket.waitForConnected(300)
    if running:
        socket.write(b"show\n")
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
    return running


def start_instance_server(on_activate: Callable[[], None]) -> QLocalServer | None:
    """创建本实例的命名管道服务；收到连接即回调唤起主窗口。

    Args:
        on_activate: 二次启动连入时执行的回调（通常是 window.wake_up）。

    Returns:
        QLocalServer 实例（调用方需持有引用防止被回收）；创建失败返回 None。
    """
    QLocalServer.removeServer(INSTANCE_KEY)  # 清理异常退出残留
    server = QLocalServer()
    if not server.listen(INSTANCE_KEY):
        return None

    def _on_new_connection() -> None:
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            if connection is not None:
                # 读掉对端写入的唤醒指令并直接唤起主窗口
                connection.readyRead.connect(lambda conn=connection: conn.readAll())
                on_activate()

    server.newConnection.connect(_on_new_connection)
    return server


# ----------------------------------------------------------------------
# 托盘图标绘制（纯 QPainter，无新素材依赖）
# ----------------------------------------------------------------------
def paint_grade_icon(grade: int, size: int = 64, dot_alpha: int | None = None) -> QIcon:
    """按健康档位绘制托盘图标。

    圆角方形底（档位颜色）+ 白色简笔硬盘；危险 / 紧急档右上角加
    白色感叹号角标（深色圆底衬托保证可读）；未检测为灰。
    v1.6：dot_alpha 非 None 时在右下角叠加体检「呼吸绿点」——
    亮(255)/暗(60) 两帧交替即闪烁效果（替代 v1.5 的旋转帧）。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base = QColor(GRADE_COLORS.get(grade, GRADE_COLORS[GRADE_UNKNOWN]))
    edge = base.darker(115)
    white = QColor("#FFFFFF")

    # ---- 底：圆角方形 ----
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(base)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 14, 14)

    # ---- 白色简笔硬盘：盘体 + 指示灯 ----
    painter.setBrush(white)
    painter.drawRoundedRect(int(size * 0.24), int(size * 0.36), int(size * 0.52), int(size * 0.30), 5, 5)
    # 盘体上的活动指示灯（底色小圆，制造「硬盘」辨识度）
    painter.setBrush(edge)
    painter.drawEllipse(int(size * 0.62), int(size * 0.52), int(size * 0.07), int(size * 0.07))
    # 盘体顶部高光线
    painter.setBrush(edge)
    painter.drawRect(int(size * 0.30), int(size * 0.42), int(size * 0.26), int(size * 0.045))

    # ---- 危险 / 紧急：右上角白色感叹号角标 ----
    if grade in (GRADE_CRITICAL, GRADE_DANGEROUS):
        badge_center_x, badge_center_y = size * 0.76, size * 0.24
        badge_radius = size * 0.19
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(edge.darker(130))
        painter.drawEllipse(
            int(badge_center_x - badge_radius),
            int(badge_center_y - badge_radius),
            int(badge_radius * 2),
            int(badge_radius * 2),
        )
        painter.setPen(white)
        font = QFont("Arial")
        font.setBold(True)
        font.setPixelSize(int(size * 0.26))
        painter.setFont(font)
        painter.drawText(
            int(badge_center_x - badge_radius),
            int(badge_center_y - badge_radius),
            int(badge_radius * 2),
            int(badge_radius * 2),
            Qt.AlignmentFlag.AlignCenter,
            "!",
        )

    # ---- 体检呼吸绿点（v1.6：替代旋转动画） ----
    if dot_alpha is not None and dot_alpha > 0:
        dot_radius = size * 0.14
        dot_center = size * 0.88
        dot_color = QColor("#35D96B")
        dot_color.setAlpha(max(30, min(255, dot_alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        # 白色描边托底，深色任务栏上也清晰
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.drawEllipse(
            int(dot_center - dot_radius - 1), int(dot_center - dot_radius - 1),
            int(dot_radius * 2 + 2), int(dot_radius * 2 + 2),
        )
        painter.setBrush(dot_color)
        painter.drawEllipse(
            int(dot_center - dot_radius), int(dot_center - dot_radius),
            int(dot_radius * 2), int(dot_radius * 2),
        )

    painter.end()
    return QIcon(pixmap)


# ----------------------------------------------------------------------
# 托盘控制器
# ----------------------------------------------------------------------
class TrayController(QObject):
    """托盘常驻图标控制器：跟随检测结果更新图标 / tooltip / 气泡通知。"""

    def __init__(self, window, version: str = "v1.1", parent: QObject | None = None) -> None:
        """window 需提供 wake_up() / _start_detection() / _set_autostart() / force_quit()。"""
        super().__init__(parent)
        self._window = window
        self._version = version
        self._icons: dict[int, QIcon] = {}
        self._last_worst_grade: int | None = None   # 最近一次检测的整体最差档位
        self._notified_grade: int | None = None     # 已气泡通知过的档位（防止重复轰炸）
        self._bg_worker = None

        self._tray = QSystemTrayIcon(self._icon(GRADE_UNKNOWN), self)
        self._tray.setToolTip(f"挖兔硬盘精灵 {version}：未检测")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

        # 「微微动」动画（v1.6）：体检时右下角绿点呼吸，900ms 一帧
        self._anim_frame = 0
        self._anim_grade = GRADE_UNKNOWN
        self._anim_mode = ""  # "" / "detect" / "pulse"
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(900)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        # 自绘气泡管理器（v1.6）：绕开系统勿扰模式
        self._toasts = None
        self._last_results: list | None = None  # tooltip 开机时长刷新用

        # 后台静默检测定时器（每 2 小时）
        self._bg_timer = QTimer(self)
        self._bg_timer.setInterval(BACKGROUND_INTERVAL_MS)
        self._bg_timer.timeout.connect(self._run_background_check)
        self._bg_timer.start()

        # 托盘悬停提示定时刷新（v1.7：开机时长随时间增长，5 分钟刷一次）
        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(5 * 60 * 1000)
        self._uptime_timer.timeout.connect(self._refresh_tooltip)
        self._uptime_timer.start()

    def _refresh_tooltip(self) -> None:
        """用最近一次检测结果重建悬停提示（开机时长实时增长）。"""
        if self._last_results is not None:
            worst = self._worst_grade(self._last_results)
            self._tray.setToolTip(self._tooltip(self._last_results, worst))

    def _ensure_toasts(self):
        """延迟创建自绘气泡管理器；创建失败返回 None（回退系统气泡）。"""
        if self._toasts is None:
            try:
                from ui.toast import ToastManager

                self._toasts = ToastManager(self)
            except Exception:
                self._toasts = None
        return self._toasts

        # 后台静默检测定时器（每 2 小时）
        self._bg_timer = QTimer(self)
        self._bg_timer.setInterval(BACKGROUND_INTERVAL_MS)
        self._bg_timer.timeout.connect(self._run_background_check)
        self._bg_timer.start()

    # ------------------------------------------------------------------
    # 「微微动」动画（v1.5）
    # ------------------------------------------------------------------
    def start_activity(self, grade: int | None = None) -> None:
        """体检开始：图标开始微微转动（直到 stop_activity）。"""
        if grade is not None:
            self._anim_grade = grade
        elif self._last_worst_grade is not None:
            self._anim_grade = self._last_worst_grade
        self._anim_mode = "detect"
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def stop_activity(self) -> None:
        """体检结束：图标恢复当前健康档位的静态颜色（v1.5.1 修复灰色残留）。"""
        self._anim_mode = ""
        self._anim_timer.stop()
        if self._last_worst_grade is not None:
            self._anim_grade = self._last_worst_grade
        grade = self._anim_grade if self._anim_grade != GRADE_UNKNOWN else GRADE_UNKNOWN
        self._tray.setIcon(self._icon(grade))

    def pulse(self, seconds: float = 2.7) -> None:
        """气泡提醒前：图标微动片刻后自动恢复（体检动画优先，不叠加）。"""
        if self._anim_timer.isActive():
            return
        self._anim_mode = "pulse"
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        QTimer.singleShot(int(seconds * 1000), self._stop_pulse)

    def _stop_pulse(self) -> None:
        if self._anim_mode == "pulse":
            self.stop_activity()

    def _on_anim_tick(self) -> None:
        """动画帧（v1.6）：绿点亮↔暗呼吸（1 秒级，替代旋转）。"""
        self._anim_frame = (self._anim_frame + 1) % 2
        if self._last_worst_grade is not None:
            self._anim_grade = self._last_worst_grade
        grade = self._anim_grade if self._anim_grade != GRADE_UNKNOWN else GRADE_UNKNOWN
        self._tray.setIcon(paint_grade_icon(grade, dot_alpha=255 if self._anim_frame == 0 else 60))

    # ------------------------------------------------------------------
    # 图标缓存
    # ------------------------------------------------------------------
    def _icon(self, grade: int) -> QIcon:
        if grade not in self._icons:
            self._icons[grade] = paint_grade_icon(grade)
        return self._icons[grade]

    # ------------------------------------------------------------------
    # 菜单
    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        from core import notify_policy
        from core.store import get_store

        menu = QMenu()

        act_open = QAction("打开主界面", menu)
        act_open.triggered.connect(self._window.wake_up)
        menu.addAction(act_open)

        act_detect = QAction("立即检测", menu)
        act_detect.triggered.connect(self._window.start_detection_from_tray)
        menu.addAction(act_detect)

        menu.addSeparator()

        self._act_autostart = QAction("开机启动", menu)
        self._act_autostart.setCheckable(True)
        self._act_autostart.setChecked(autostart.is_enabled())
        self._act_autostart.toggled.connect(self._window.set_autostart)
        menu.addAction(self._act_autostart)

        # ---- 提醒设置（v1.5：从主界面移到托盘，保持面板简洁） ----
        store = get_store()
        remind_menu = menu.addMenu("提醒设置")
        self._act_notify = QAction("气泡提醒", remind_menu)
        self._act_notify.setCheckable(True)
        self._act_notify.setChecked(bool(store.get_setting("notify_enabled", True)))
        self._act_notify.toggled.connect(self._on_notify_toggled)
        remind_menu.addAction(self._act_notify)
        remind_menu.addSeparator()
        self._profile_actions: list[QAction] = []
        self._profile_action_by_key: dict[str, QAction] = {}
        for key in notify_policy.PROFILE_ORDER:
            act = QAction(notify_policy.PROFILE_LABELS[key], remind_menu)
            act.setCheckable(True)
            act.setChecked(
                str(store.get_setting("notify_profile", notify_policy.PROFILE_GENTLE)) == key
            )
            act.toggled.connect(lambda checked, k=key: self._on_profile_toggled(k, checked))
            remind_menu.addAction(act)
            self._profile_actions.append(act)
            self._profile_action_by_key[key] = act

        menu.addSeparator()

        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self._window.force_quit)
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)

    def _test_bubble(self) -> None:
        """调试用：立即弹一张自绘气泡（正式版菜单已移除入口）。"""
        from core import tender

        title, text = tender.pick("ok")
        self.notify_custom(f"测试 · {title}", text, QSystemTrayIcon.MessageIcon.Information)

    def _on_notify_toggled(self, checked: bool) -> None:
        """托盘里的气泡提醒总开关（与数据设置保持同步）。"""
        from core.store import get_store

        get_store().set_setting("notify_enabled", bool(checked))

    def _on_profile_toggled(self, key: str, checked: bool) -> None:
        """五种提醒方案单选（勾选一个，取消其余）。"""
        from core import notify_policy
        from core.store import get_store

        if not checked:
            # 取消勾选：恢复当前生效方案，避免出现「全不选」
            current = str(get_store().get_setting("notify_profile", notify_policy.PROFILE_GENTLE))
            act = self._profile_action_by_key.get(current)
            if act is not None:
                act.blockSignals(True)
                act.setChecked(True)
                act.blockSignals(False)
            return
        get_store().set_setting("notify_profile", key)
        for profile_key, act in self._profile_action_by_key.items():
            if profile_key != key and act.isChecked():
                act.blockSignals(True)
                act.setChecked(False)
                act.blockSignals(False)

    def sync_autostart(self, enabled: bool) -> None:
        """主界面开关机启动后同步托盘菜单勾选状态（避免信号回环用 blockSignals）。"""
        self._act_autostart.blockSignals(True)
        self._act_autostart.setChecked(enabled)
        self._act_autostart.blockSignals(False)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _on_activated(self, reason) -> None:
        """单击托盘图标：打开 / 唤起主窗口。"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._window.wake_up()

    def notify_minimized(self) -> None:
        """主窗口首次最小化到托盘时的气泡提示。"""
        self._tray.showMessage(
            "挖兔硬盘精灵",
            "已最小化到托盘，检测仍在后台守护中。点击托盘图标可重新打开，退出请使用托盘菜单。",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def notify_custom(self, title: str, text: str, icon=QSystemTrayIcon.MessageIcon.Information,
                      open_on_click: bool | None = None) -> None:
        """通知入口（v1.7）：自绘气泡；点击行为按级别分级——

        info（健康）：点击仅关闭气泡；warn/danger：点击打开主界面。
        open_on_click 显式传入时优先生效。
        """
        level_map = {
            QSystemTrayIcon.MessageIcon.Critical: "danger",
            QSystemTrayIcon.MessageIcon.Warning: "warn",
            QSystemTrayIcon.MessageIcon.Information: "info",
        }
        level = level_map.get(icon, "info")
        if open_on_click is None:
            open_on_click = level in ("warn", "danger")
        self.pulse(2.7)  # 提醒前图标绿点微闪
        toasts = self._ensure_toasts()
        if toasts is not None:
            toasts.push(level, title, text, on_click=self._window.wake_up if open_on_click else None)
        else:
            self._tray.showMessage(title, text, icon, 5000)

    # ------------------------------------------------------------------
    # 结果更新
    # ------------------------------------------------------------------
    def update_results(self, results: list[dict], notify_if_worse: bool = False) -> None:
        """用检测结果刷新托盘图标与 tooltip。

        Args:
            results: DetectWorker 的输出列表（每项含 disk / verdict）。
            notify_if_worse: True 时（仅后台定时检测），整体等级比上次
                更差则弹一次气泡通知，不重复轰炸。
        """
        self._last_results = list(results or [])
        worst = self._worst_grade(results)
        self._tray.setIcon(self._icon(worst))
        self._tray.setToolTip(self._tooltip(results, worst))
        previous = self._last_worst_grade
        self._last_worst_grade = worst
        if notify_if_worse and worst != GRADE_UNKNOWN and worst < 4:
            # 比上次更差、且该档位从未通知过，才弹一次
            if (previous is None or worst < previous) and worst != self._notified_grade:
                self._notified_grade = worst
                self._tray.showMessage(
                    "硬盘健康预警",
                    f"硬盘状态变差：当前最低「{GRADE_LABELS.get(worst, '未知')}」档，建议打开主界面查看详情并备份重要数据。",
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )

    @staticmethod
    def _worst_grade(results: list[dict]) -> int:
        """取所有盘中最差的六档等级；无结果返回 GRADE_UNKNOWN。"""
        grades = [
            grade_of_verdict(result.get("verdict"))
            for result in results or []
            if result.get("verdict")
        ]
        valid = [g for g in grades if g != GRADE_UNKNOWN]
        return min(valid) if valid else GRADE_UNKNOWN

    def _tooltip(self, results: list[dict], worst: int) -> str:
        """托盘悬停提示（v1.7）：检测摘要 + 开机时长关怀句。"""
        from core.sysidle import uptime_text

        head = f"挖兔硬盘精灵 {self._version}"
        total = len(results or [])
        if total == 0 or worst == GRADE_UNKNOWN:
            return f"{head}：未检测到硬盘信息"
        scores = [
            int((result.get("verdict") or {}).get("score") or 0)
            for result in results
            if result.get("verdict")
        ]
        min_score = min(scores) if scores else 0
        all_healthy = all(
            str((result.get("verdict") or {}).get("level")) == "healthy" for result in results
        )
        status = "全部健康" if all_healthy else f"最低「{GRADE_LABELS.get(worst, '未知')}」"
        uptime = uptime_text()
        return (
            f"{head}：共 {total} 块盘，{status}（最低 {min_score} 分）\n"
            f"硬盘很健康，您开机至今已经 {uptime}。"
        )

    # ------------------------------------------------------------------
    # 后台静默检测
    # ------------------------------------------------------------------
    def _run_background_check(self) -> None:
        """每 2 小时后台完整检测一次：只更新托盘，不弹窗。

        v1.3 空闲门控：用户闲置 ≥5 分钟或 CPU <25% 才执行；系统繁忙
        （用户正在干活）则推迟 15 分钟重试，绝不与前台应用抢资源。
        """
        from core import sysidle

        # 主窗口正在检测或上一轮后台检测未结束：跳过本轮
        if self._window.is_detecting() or (self._bg_worker is not None and self._bg_worker.isRunning()):
            return
        if not sysidle.system_is_idle():
            QTimer.singleShot(15 * 60 * 1000, self._run_background_check)
            return
        from ui.main_window import DetectWorker

        self._bg_worker = DetectWorker(None)
        self._bg_worker.step_started.connect(lambda _index: None)
        self._bg_worker.step_result.connect(lambda _i, _ok, _text: None)
        self._bg_worker.detect_finished.connect(self._on_bg_finished)
        self._bg_worker.detect_failed.connect(lambda _msg: None)
        self._bg_worker.start()

    def _on_bg_finished(self, results: list) -> None:
        """后台检测完成：刷新托盘 + 写入体检记录 + 按提醒方案弹温度气泡。"""
        from core import notify_policy, tender
        from core.store import get_store
        from core.verdict import summarize

        store = get_store()
        self.update_results(list(results), notify_if_worse=False)
        record = getattr(self._window, "record_detection_history", None)
        if callable(record):
            record(list(results), True, 0.0, source="定时体检")

        results = list(results)
        if not results:
            return
        summary = summarize(results)
        profile = str(store.get_setting("notify_profile", notify_policy.PROFILE_GENTLE))
        worst_space = self._worst_space_pct(results)
        max_temp = self._max_temp(results)
        has_danger = summary["danger"] > 0
        has_warn = summary["warning"] > 0

        if worst_space is not None and worst_space < 10:
            category = "space_critical"
        elif has_danger:
            category = "danger"
        elif has_warn:
            category = "warn"
        elif worst_space is not None and worst_space < 20:
            category = "space_low"
        elif isinstance(max_temp, int) and max_temp >= 65:
            category = "hot"
        else:
            category = "ok"

        if category == "ok":
            if not notify_policy.should_notify_healthy(profile):
                return
        elif not notify_policy.on_worse_notify(profile):
            return

        title, text = tender.pick(category)
        if profile == notify_policy.PROFILE_WARM:
            status_bits = []
            if isinstance(max_temp, int) and max_temp > 0:
                status_bits.append(f"最高温 {max_temp}°C")
            if worst_space is not None:
                status_bits.append(f"最紧空间剩 {worst_space:.0f}%")
            if status_bits:
                text += "（" + "，".join(status_bits) + "）"
        elif profile == notify_policy.PROFILE_EXTRA and category == "ok":
            tip_index = int(store.get_setting("last_tip_index", -1))
            tip, tip_index = notify_policy.extra_line(profile, tip_index)
            store.set_setting("last_tip_index", tip_index)
            text = f"{text}\n{tip}"

        if category == "ok":
            notify_policy.mark_healthy_notified(profile)
        icon = (
            QSystemTrayIcon.MessageIcon.Critical if category == "danger"
            else QSystemTrayIcon.MessageIcon.Warning if category in ("warn", "space_critical", "hot")
            else QSystemTrayIcon.MessageIcon.Information
        )
        self.notify_custom(title, text, icon)

        if self._bg_worker is not None:
            self._bg_worker.deleteLater()
            self._bg_worker = None

    @staticmethod
    def _worst_space_pct(results: list[dict]) -> float | None:
        """所有卷中最紧张的剩余空间百分比；取不到返回 None。"""
        worst: float | None = None
        for result in results:
            for volume in result.get("all_volumes") or []:
                pct = volume.get("free_pct")
                if isinstance(pct, (int, float)) and (worst is None or pct < worst):
                    worst = float(pct)
        return worst

    @staticmethod
    def _max_temp(results: list[dict]) -> int | None:
        """所有盘中的最高当前温度。"""
        temps: list[int] = []
        for result in results:
            for key_path in (("counters", "Temperature"), ("nvme_health", "temperature_c")):
                value = (result.get(key_path[0]) or {}).get(key_path[1])
                if isinstance(value, int) and value > 0:
                    temps.append(value)
        return max(temps) if temps else None

    # ------------------------------------------------------------------
    def hide_tray(self) -> None:
        """退出前隐藏托盘图标。"""
        self._bg_timer.stop()
        self._uptime_timer.stop()
        self._tray.hide()
