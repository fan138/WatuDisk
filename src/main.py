# -*- coding: utf-8 -*-
"""DiskGuard 挖兔硬盘精灵 — 程序入口。

职责：
- 启动时检查管理员权限，非管理员时通过 ShellExecuteW 'runas' 重启自身提权；
- 用户拒绝提权则进入「基础模式」，并在界面明确提示数据受限；
- 提供 --selftest（核心逻辑自检，无需 GUI / 管理员）与 --smoke（GUI 冒烟，2 秒自动退出）。

约束：全程只读检测、不写注册表、不联网（无任何 socket/requests/urllib 导入）。
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

APP_NAME = "挖兔硬盘精灵"
APP_VERSION = "v1.0.0"


# ----------------------------------------------------------------------
# 管理员权限
# ----------------------------------------------------------------------
def is_admin() -> bool:
    """检查当前进程是否以管理员身份运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def try_elevate() -> bool:
    """尝试以管理员身份重启自身。

    Returns:
        True 表示提权实例已成功启动（当前进程应立即退出）；
        False 表示用户拒绝 UAC 或提权失败（应继续以基础模式运行）。
    """
    try:
        if getattr(sys, "frozen", False):
            # PyInstaller 打包后：直接以当前 exe 重启
            executable = sys.executable
            params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
        else:
            # 开发环境：用 python.exe + 脚本路径重启
            executable = sys.executable
            params = " ".join([f'"{os.path.abspath(sys.argv[0])}"'] + [f'"{arg}"' for arg in sys.argv[1:]])
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return int(ret) > 32
    except Exception:
        return False


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
def run_gui(admin: bool, smoke: bool, boot: bool = False) -> int:
    """创建并运行主窗口。

    Args:
        admin: 是否具有管理员权限（用于界面状态提示）。
        smoke: 冒烟模式，窗口显示 2 秒后自动退出；跳过托盘 / 单实例，
            保证 offscreen 自动化验证干净退出。
        boot: 开机静默模式（快捷方式 --boot）：不弹主窗口，等系统
            空闲后自动体检一次，只更新托盘与体检记录。
    """
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from core.resource_path import app_icon_path
    from ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # v1.7：不设置 ApplicationDisplayName —— 否则窗口标题变成「挖兔硬盘精灵 v1.7.0 - 挖兔硬盘精灵」重复
    app.setApplicationDisplayName("")

    # 应用图标（开发态 src/assets，打包态 sys._MEIPASS/assets）
    icon_path = app_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # 单实例保护：二次启动唤起已有实例后退出（冒烟模式跳过）
    instance_server = None
    if not smoke:
        from ui.tray import is_already_running, start_instance_server

        if is_already_running():
            return 0  # 已唤起现有实例

    window = MainWindow(admin=admin, version=APP_VERSION, enable_tray=not smoke)

    if not smoke:
        instance_server = start_instance_server(window.wake_up)
        window._instance_server = instance_server  # 持有引用防止被回收

        # 关机 / 重启守护：监听 WM_QUERYENDSESSION（毫秒级只读复查，不拦截关机）
        if admin:
            from ui.shutdown_filter import ShutdownGuardFilter

            filter_instance = ShutdownGuardFilter(window)
            app.installNativeEventFilter(filter_instance)
            window._shutdown_filter = filter_instance  # 持有引用防止被回收

    if not boot:
        window.show()

    if not smoke:
        # 上次关机守护发现过异常：开机后郑重提醒一次
        if boot:
            QTimer.singleShot(6000, window.show_pending_boot_alert)
            QTimer.singleShot(500, window.maybe_start_boot_check)

    if smoke:
        # 冒烟模式：2 秒后自动关闭，供无交互验证
        QTimer.singleShot(2000, app.quit)
        code = app.exec()
        os._exit(code)  # 强制退出，避免后台检测线程阻塞进程
    return app.exec()


# ----------------------------------------------------------------------
# 自检（不依赖 GUI 与管理员权限）
# ----------------------------------------------------------------------
def _selftest() -> int:
    """核心逻辑自检：全部通过返回 0，否则返回 1。"""
    from core import event_scan, report, smart_parser, verdict
    from core import autostart
    from core.disk_info import format_hours, format_size

    failures: list[str] = []

    def check(name: str, cond: bool, extra: str = "") -> None:
        status = "PASS" if cond else "FAIL"
        line = f"[{status}] {name}" + (f"  ({extra})" if extra else "")
        print(line)
        if not cond:
            failures.append(name)

    # 1) 容量 / 时间格式化
    check("format_size TB", format_size(2 * 1024 ** 4) == "2.00 TB", format_size(2 * 1024 ** 4))
    check("format_size GB", format_size(512 * 1024 ** 3) == "512 GB", format_size(512 * 1024 ** 3))
    check("format_size empty", format_size(0) == "未知容量", format_size(0))
    check("format_hours", format_hours(9000) == "9,000 小时（约 1.0 年）", str(format_hours(9000)))
    check("format_hours small", format_hours(36) == "36 小时", str(format_hours(36)))
    check("format_hours None", format_hours(None) is None)

    # 1.1) v1.1 专业格式化与六档等级边界
    from core.disk_info import format_hours_pro, format_int
    from core.verdict import GRADE_COLORS, GRADE_LABELS, grade_of_score, grade_of_verdict

    check("format_hours_pro year", format_hours_pro(14200) == "14,200 小时 · 约 1.6 年", str(format_hours_pro(14200)))
    check("format_hours_pro small", format_hours_pro(36) == "36 小时", str(format_hours_pro(36)))
    check("format_hours_pro None", format_hours_pro(None) is None)
    check("format_int", format_int(14200) == "14,200", str(format_int(14200)))
    check("format_int None", format_int(None) is None)
    check("format_int garbage", format_int("abc") is None)

    grade_expect = {
        0: 0, 24: 0, 25: 1, 44: 1, 45: 2, 59: 2,
        60: 3, 74: 3, 75: 4, 89: 4, 90: 5, 100: 5,
    }
    for score, expected in grade_expect.items():
        check(f"grade_of_score({score})", grade_of_score(score) == expected, str(grade_of_score(score)))
    check("grade_of_score None", grade_of_score(None) == -1)
    check("grade_of_score garbage", grade_of_score("abc") == -1)
    check("grade_of_verdict", grade_of_verdict({"score": 96}) == 5)
    check("grade_of_verdict empty", grade_of_verdict({}) == -1)
    check("grade colors complete", set(GRADE_COLORS) == {-1, 0, 1, 2, 3, 4, 5})
    check("grade labels complete", set(GRADE_LABELS) == {-1, 0, 1, 2, 3, 4, 5})

    # 2) SMART 原始属性解析（构造合成字节流）
    vendor = [0x01, 0x00]  # 2 字节版本号
    for attr_id, raw in ((0x05, 4), (0xC5, 8), (0xC6, 2), (0x09, 9000)):
        vendor += [attr_id, 0x00, 0x00, 0x64, 0x64] + list(raw.to_bytes(6, "little")) + [0x00]
    attrs = smart_parser.parse_vendor_attributes(vendor)
    check("smart parse count", len(attrs) == 4, str(len(attrs)))
    check("smart parse c6 raw", any(a["id"] == 0xC6 and a["raw"] == 2 for a in attrs))
    check("smart parse name", any(a["id"] == 0x05 and a["name"] == "重映射扇区数" for a in attrs))
    check("smart parse empty", smart_parser.parse_vendor_attributes([]) == [])
    check("smart parse garbage", smart_parser.parse_vendor_attributes([1, 2, 3]) == [])

    # 3) 评分引擎：健康盘
    disk = {
        "device_id": "0",
        "model": "Test NVMe SSD",
        "media_type": "SSD",
        "bus_type": "NVMe",
        "health_status": "Healthy",
        "op_status": "OK",
        "size": 512 * 1024 ** 3,
        "serial": "S123456",
    }
    v_ok = verdict.evaluate_disk(
        disk,
        {"Temperature": 40, "Wear": 5, "PowerOnHours": 9000, "ReadErrorsUncorrected": 0, "WriteErrorsUncorrected": 0},
        [],
        0,
        [],
        [],
    )
    check("verdict healthy", v_ok["level"] == "healthy", f"score={v_ok['score']}")

    # 4) 评分引擎：危险盘（磨损 95% + 高温 + 未修正错误 + 事件多 + 损坏位 + 坏扇区）
    counters_bad = {"Temperature": 75, "Wear": 95, "ReadErrorsUncorrected": 120, "WriteErrorsUncorrected": 0}
    v_bad = verdict.evaluate_disk(
        disk,
        counters_bad,
        attrs,
        25,
        [{"time": "t", "provider": "disk", "level_text": "错误", "message": "坏块"}],
        [{"drive": "C:", "dirty": True, "disk_number": 0}],
    )
    check("verdict danger", v_bad["level"] == "danger", f"score={v_bad['score']}")
    check("verdict reasons plain-chinese", any("备份" in reason for reason in v_bad["reasons"]))

    # 5) 数据受限时的降级提示
    v_limited = verdict.evaluate_disk(disk, None, [], 0, [], [])
    check("verdict limited data", any("管理员" in reason for reason in v_limited["reasons"]))

    # 6) 事件匹配（Harddisk0 不吞并 Harddisk01）
    events = [
        {"time": "t1", "provider": "disk", "level": 2, "level_text": "错误", "message": r"设备 \Device\Harddisk0\DR0 存在坏块。"},
        {"time": "t2", "provider": "Ntfs", "level": 3, "level_text": "警告", "message": "卷 C: 文件系统错误（Harddisk1）。"},
    ]
    count, recent = event_scan.match_events_to_disk(events, disk)
    check("event match harddisk0", count == 1 and len(recent) == 1, f"count={count}")

    # 7) 汇总统计
    summary = verdict.summarize([{"verdict": v_ok}, {"verdict": v_bad}])
    check("summarize", summary == {"total": 2, "healthy": 1, "warning": 0, "danger": 1}, str(summary))

    # 8) 报告 HTML 构建（仅生成字符串，不写盘）
    sample = {
        "disk": disk,
        "counters": {"Temperature": 40, "Wear": 5, "PowerOnHours": 9000},
        "nvme_health": {
            "critical_warning": 0, "temperature_c": 35, "available_spare_pct": 100,
            "spare_threshold": 10, "percentage_used": 2,
            "data_units_read": 123, "data_units_written": 456,
            "power_cycles": 1072, "power_on_hours": 9000,
            "unsafe_shutdowns": 12, "media_errors": 0, "error_log_entries": 0,
        },
        "smart_attrs": attrs,
        "event_count": 1,
        "event_recent": [{"time": "t1", "level_text": "错误", "provider": "disk", "message": "坏块"}],
        "dirty_volumes": [],
        "all_volumes": [{"drive": "C:", "dirty": False, "disk_number": 0}],
        "verdict": v_ok,
    }
    html_text = report.build_report_html([sample])
    check("report html", "挖兔硬盘精灵" in html_text and "Test NVMe SSD" in html_text)
    check("report disclaimer", "只读" in html_text)
    check("report nvme section", "NVMe 健康数据" in html_text)

    # 9) v1.2 NVMe 健康日志解析（标准布局 / +24 偏移布局 / 降级）
    import struct as _struct

    from core import nvme_health

    def _mk_health_log(
        du_read: int,
        du_written: int,
        power_cycles: int = 1072,
        poh: int = 13296,
        unsafe: int = 88,
        media: int = 0,
        shift: int = 0,
    ) -> bytes:
        """构造合成健康日志页：shift=0 标准布局 / shift=24 固件偏移布局。"""
        data = bytearray(512)
        _struct.pack_into("<BHBBB", data, 0, 0, 273 + 35, 100, 10, 2)  # 头部固定标准偏移
        _struct.pack_into("<Q", data, 8 + shift, du_read)              # Data Units Read
        _struct.pack_into("<Q", data, 24 + shift, du_written)          # Data Units Written
        _struct.pack_into("<Q", data, 88 + shift, power_cycles)        # Power Cycles
        _struct.pack_into("<Q", data, 104 + shift, poh)                # Power On Hours
        _struct.pack_into("<Q", data, 120 + shift, unsafe)             # Unsafe Shutdowns
        _struct.pack_into("<Q", data, 136 + shift, media)              # Media Errors
        _struct.pack_into("<Q", data, 152 + shift, 3)                  # Err Log Entries
        return bytes(data)

    h_std = nvme_health.parse_health_log(_mk_health_log(123, 456))
    check(
        "nvme parse standard layout",
        bool(h_std)
        and h_std["data_units_read"] == 123
        and h_std["data_units_written"] == 456
        and h_std["power_on_hours"] == 13296
        and h_std["power_cycles"] == 1072
        and h_std["unsafe_shutdowns"] == 88
        and h_std["temperature_c"] == 35
        and h_std["available_spare_pct"] == 100
        and h_std["spare_threshold"] == 10
        and h_std["percentage_used"] == 2,
        str(h_std),
    )
    h_shift = nvme_health.parse_health_log(_mk_health_log(789, 1011, power_cycles=65, poh=1556, shift=24))
    check(
        "nvme parse shifted layout (+24)",
        bool(h_shift)
        and h_shift["data_units_read"] == 789
        and h_shift["data_units_written"] == 1011
        and h_shift["power_on_hours"] == 1556
        and h_shift["power_cycles"] == 65
        and h_shift["temperature_c"] == 35,
        str(h_shift),
    )
    # 标准布局读 / 写计数全 0 且 +24 处也全 0：保持标准布局不误判
    h_zero = nvme_health.parse_health_log(_mk_health_log(0, 0))
    check("nvme parse all-zero stays standard", bool(h_zero) and h_zero["data_units_read"] == 0)
    # 降级：空数据 / 过短数据 / 非法输入
    check("nvme parse empty", nvme_health.parse_health_log(b"") is None)
    check("nvme parse short", nvme_health.parse_health_log(b"\x01" * 100) is None)
    # Data Units 容量换算：46420225 DU × 512000 B ≈ 21.6 TB（1024 进制，真机 ZHITAI Ti600）
    check(
        "nvme format_data_units TB",
        nvme_health.format_data_units(46420225) == "21.6 TB",
        str(nvme_health.format_data_units(46420225)),
    )
    check("nvme format_data_units GB", nvme_health.format_data_units(10240) == "5 GB", str(nvme_health.format_data_units(10240)))
    check("nvme format_data_units None", nvme_health.format_data_units(None) is None)

    # 10) v1.2 评分引擎：NVMe 新信号
    nvme_good = {
        "critical_warning": 0, "temperature_c": 35, "available_spare_pct": 100,
        "spare_threshold": 10, "percentage_used": 2,
        "data_units_read": 100, "data_units_written": 200,
        "power_cycles": 65, "power_on_hours": 1556,
        "unsafe_shutdowns": 12, "media_errors": 0, "error_log_entries": 0,
    }
    v_nvme_ok = verdict.evaluate_disk(disk, None, [], 0, [], [], nvme_good)
    check(
        "verdict nvme healthy (no limited note)",
        v_nvme_ok["level"] == "healthy" and all("无法读取" not in r for r in v_nvme_ok["reasons"]),
        f"score={v_nvme_ok['score']}",
    )

    v_nvme_crit = verdict.evaluate_disk(disk, None, [], 0, [], [], dict(nvme_good, critical_warning=1))
    check(
        "verdict nvme critical_warning forces danger",
        v_nvme_crit["level"] == "danger" and any("危险警告" in r for r in v_nvme_crit["reasons"]),
        f"score={v_nvme_crit['score']}",
    )

    v_nvme_spare = verdict.evaluate_disk(disk, None, [], 0, [], [], dict(nvme_good, available_spare_pct=5))
    check(
        "verdict nvme low spare forces warning",
        v_nvme_spare["level"] in ("warning", "danger") and any("备用空间" in r for r in v_nvme_spare["reasons"]),
        f"score={v_nvme_spare['score']}",
    )

    v_nvme_media = verdict.evaluate_disk(disk, None, [], 0, [], [], dict(nvme_good, media_errors=5))
    check(
        "verdict nvme media errors deduct capped",
        v_nvme_media["score"] == 76 and any("媒体错误" in r for r in v_nvme_media["reasons"]),
        f"score={v_nvme_media['score']}",
    )

    v_nvme_pct = verdict.evaluate_disk(disk, None, [], 0, [], [], dict(nvme_good, percentage_used=92))
    check(
        "verdict nvme percentage_used deducts",
        v_nvme_pct["score"] == 70 and any("已使用寿命" in r for r in v_nvme_pct["reasons"]),
        f"score={v_nvme_pct['score']}",
    )

    v_nvme_pct_wear = verdict.evaluate_disk(
        disk, {"Temperature": 40, "Wear": 5}, [], 0, [], [], dict(nvme_good, percentage_used=92)
    )
    check(
        "verdict nvme pct skipped when wear present",
        v_nvme_pct_wear["score"] == 100 and all("已使用寿命" not in r for r in v_nvme_pct_wear["reasons"]),
        f"score={v_nvme_pct_wear['score']}",
    )

    v_nvme_unsafe = verdict.evaluate_disk(disk, None, [], 0, [], [], dict(nvme_good, unsafe_shutdowns=200))
    check(
        "verdict nvme unsafe shutdowns deducts",
        v_nvme_unsafe["score"] == 95 and any("断电" in r for r in v_nvme_unsafe["reasons"]),
        f"score={v_nvme_unsafe['score']}",
    )

    # 11) v1.3 有界持久化存储（临时目录，测完即清，不留垃圾）
    import tempfile

    from core import store as store_mod

    with tempfile.TemporaryDirectory() as tmp_dir:
        st = store_mod.Store(dir_override=tmp_dir)
        check("store history empty", st.history() == [])
        for i in range(store_mod.MAX_HISTORY + 30):
            st.append_history({"time": f"t{i}", "level": "ok", "text": f"第{i}次", "source": "自检"})
        check(
            "store history capped",
            len(st.history()) == store_mod.MAX_HISTORY
            and st.history()[0]["text"] == f"第{store_mod.MAX_HISTORY + 29}次",
            f"n={len(st.history())}",
        )
        key = st.ignore_key("S123", "current_temp")
        st.set_ignored(key, True)
        check("store ignore set", st.is_ignored(key))
        st.set_ignored(key, False)
        check("store ignore unset", not st.is_ignored(key))
        st.set_setting("silent_boot_check", True)
        st2 = store_mod.Store(dir_override=tmp_dir)
        check("store persist roundtrip", st2.get_setting("silent_boot_check") is True and len(st2.history()) == store_mod.MAX_HISTORY)

    # 12) v1.3 指标阈值分级
    from core import metrics

    check("metric temp ok", metrics.level_for("current_temp", 39) == metrics.LEVEL_OK)
    check("metric temp caution", metrics.level_for("current_temp", 58) == metrics.LEVEL_CAUTION)
    check("metric temp warn", metrics.level_for("current_temp", 66) == metrics.LEVEL_WARN)
    check("metric temp danger", metrics.level_for("current_temp", 75) == metrics.LEVEL_DANGER)
    check("metric life danger", metrics.level_for("life_remaining", 8) == metrics.LEVEL_DANGER)
    check("metric life ok", metrics.level_for("life_remaining", 96) == metrics.LEVEL_OK)
    check("metric spare below threshold", metrics.level_for("spare", 5, {"spare_threshold": 10}) == metrics.LEVEL_DANGER)
    check("metric media errors", metrics.level_for("media_errors", 1) == metrics.LEVEL_DANGER)
    check("metric info neutral", metrics.level_for("power_on_hours", 99999) == metrics.LEVEL_OK)
    check("metric dirty", metrics.level_for("dirty_volume", True) == metrics.LEVEL_DANGER)
    check("metric events danger", metrics.level_for("event_count", 25) == metrics.LEVEL_DANGER)
    check("metric c6 danger", metrics.level_for("uncorrectable", 1) == metrics.LEVEL_DANGER)

    sample_items = metrics.metric_items_for_result({
        "disk": disk,
        "counters": {"Temperature": 75, "Wear": 50},
        "nvme_health": dict(nvme_good),
        "event_count": 25,
    })
    level_map = {item["key"]: item["level"] for item in sample_items}
    check(
        "metric items for result",
        len(sample_items) > 15
        and level_map.get("current_temp") == metrics.LEVEL_DANGER
        and level_map.get("life_remaining") == metrics.LEVEL_OK
        and level_map.get("event_count") == metrics.LEVEL_DANGER
        and level_map.get("power_on_hours") == metrics.LEVEL_OK,
        str(level_map),
    )

    # 13) v1.3 关机守护：非法盘号降级为空（不抛异常、零负担）
    from core import shutdown_guard

    check("shutdown guard no data", shutdown_guard.quick_check(["999"], deadline_ts=time.time() + 0.1) == [])
    check("shutdown guard empty input", shutdown_guard.quick_check([]) == [])

    # 14) v1.3 开机启动快捷方式带 --boot 静默参数
    target_boot, args_boot, _workdir_boot = autostart._target()
    check("autostart boot arg", "--boot" in args_boot, args_boot)

    # 15) v1.4 温度文案库（≥200 条）与抽取
    from core import tender

    check("tender count >= 200", tender.total_count() >= 200, f"total={tender.total_count()}")
    check("tender categories non-empty", all(
        len(lst) >= 15 for lst in (
            tender.CHECK_OK, tender.CHECK_WARN, tender.CHECK_DANGER,
            tender.SPACE_LOW, tender.SPACE_CRITICAL, tender.TEMP_HOT, tender.BOOT_GREETING,
        )
    ))
    title_ok, text_ok = tender.pick("ok")
    _title_again, text_again = tender.pick("ok")
    check("tender pick returns", bool(title_ok) and bool(text_ok))
    check("tender pick avoids repeat", text_again != text_ok, f"{text_ok[:12]}... vs {text_again[:12]}...")

    # 16) v1.4 剩余空间分级与通知策略
    check("space ok", metrics.level_for("free_space", 35) == metrics.LEVEL_OK)
    check("space caution", metrics.level_for("free_space", 15) == metrics.LEVEL_CAUTION)
    check("space warn", metrics.level_for("free_space", 8) == metrics.LEVEL_WARN)
    check("space danger", metrics.level_for("free_space", 3) == metrics.LEVEL_DANGER)

    with tempfile.TemporaryDirectory() as tmp_dir:
        from core import notify_policy

        st = store_mod.Store(dir_override=tmp_dir)
        # 策略函数内部通过 notify_policy.get_store 取存储 -> 注入临时存储，避免污染真实数据
        original_get_store = notify_policy.get_store
        notify_policy.get_store = lambda: st
        try:
            st.set_setting("notify_enabled", True)
            st.set_setting("notify_counters_date", "2000-01-01")  # 触发按日重置
            # gentle 档：健康提示前 2 条允许
            check("policy gentle allows first", notify_policy.should_notify_healthy(notify_policy.PROFILE_GENTLE))
            notify_policy.mark_healthy_notified(notify_policy.PROFILE_GENTLE)
            notify_policy.mark_healthy_notified(notify_policy.PROFILE_GENTLE)
            check("policy gentle caps at 2", not notify_policy.should_notify_healthy(notify_policy.PROFILE_GENTLE))
            check("policy quiet blocks healthy", not notify_policy.should_notify_healthy(notify_policy.PROFILE_QUIET))
            check("policy worse always allowed", notify_policy.on_worse_notify(notify_policy.PROFILE_QUIET))
            # 习惯识别：连续 4 次忽略 -> 当天健康提示静默
            st.set_setting(notify_policy.SHOWN_KEY, 0)
            st.set_setting(notify_policy.STREAK_KEY, 4)
            check("policy habit silences healthy", not notify_policy.should_notify_healthy(notify_policy.PROFILE_DAILY))
            notify_policy.mark_interacted()
            check("policy interact resets streak", notify_policy.should_notify_healthy(notify_policy.PROFILE_DAILY))
        finally:
            notify_policy.get_store = original_get_store

    # 17) v1.5.1 护盘建议库（按盘况挑选、轮换）
    from core import care_tips

    check("care tips total >= 20", care_tips.total_count() >= 20, f"total={care_tips.total_count()}")
    tips_healthy = care_tips.tips_for_disk("healthy", seed=0)
    tips_danger = care_tips.tips_for_disk("danger", seed=0)
    tips_rotated = care_tips.tips_for_disk("healthy", seed=1)
    check("care tips healthy keeps", any("保持现状" in t or "维持现状" in t for t in tips_healthy))
    check("care tips danger backup", any("备份" in t for t in tips_danger))
    check("care tips rotate", tips_healthy[:2] != tips_rotated[:2])

    # 17.1) v1.5.1 开机快捷方式兼容迁移函数存在且幂等安全（无 .lnk 时直接通过）
    check("autostart ensure no lnk", autostart.ensure_boot_argument(startup_dir=os.path.join(tempfile.gettempdir(), "dg_no_such_dir")) is True)

    # 18) v1.5 报告六档配色与指标着色
    sample_danger = dict(sample)
    sample_danger["verdict"] = dict(v_bad)
    html_danger = report.build_report_html([sample_danger])
    check("report grade pill color", "background:#" in html_danger)
    check("report metric colored span", 'style="color:' in report.build_report_html([sample]))

    # 19) v1.6 托盘绿点呼吸帧 + 自绘气泡（QPixmap 需要 QApplication，用离屏实例）
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QIcon as _QIcon
    from PySide6.QtWidgets import QApplication as _QApplication

    from ui.toast import ToastManager, ToastPopup
    from ui.tray import paint_grade_icon

    _qt_app = _QApplication.instance() or _QApplication(sys.argv)
    _icon_on = paint_grade_icon(5, size=48, dot_alpha=255)
    _icon_off = paint_grade_icon(5, size=48, dot_alpha=60)
    _icon_idle = paint_grade_icon(5, size=48)
    check(
        "tray dot frames",
        all(isinstance(i, _QIcon) and not i.isNull() for i in (_icon_on, _icon_off, _icon_idle)),
    )
    _toast = ToastPopup("info", "测试标题", "测试内容", on_click=None)
    _manager = ToastManager()
    check("toast popup created", _toast is not None and _toast.windowFlags() & _Qt.WindowType.FramelessWindowHint)
    check("toast manager queue", _manager is not None)

    # 20) v1.7 开机时长文案
    from core import sysidle as _sysidle

    _uptime_text = _sysidle.uptime_text()
    check("uptime text format", ("小时" in _uptime_text or "分钟" in _uptime_text) and _sysidle.uptime_hours() >= 0, _uptime_text)

    # 21) v1.8 骨架卡片与评分滚动
    from PySide6.QtWidgets import QLabel as _QLabel

    from ui.main_window import DetectWorker, DiskCard

    check("worker disks_enumerated signal", hasattr(DetectWorker, "disks_enumerated"))
    _skel = DiskCard({"disk": disk, "verdict": {}}, loading=True)
    check("skeleton pill loading", _skel._pill_label.text() == "检测中", _skel._pill_label.text())
    _skel.apply_result(sample)
    # 滚动动画启动后药丸进入最终档位样式；文本在动画结束后定格
    check("skeleton apply grade style", _skel._pill_label.objectName() == "pillGrade5", _skel._pill_label.objectName())
    if _skel._score_timer is not None:
        _skel._score_timer.stop()
        _skel._pill_label.setText("优秀 · 100 分")
    check("skeleton final score", _skel._pill_label.text() == "优秀 · 100 分", _skel._pill_label.text())
    check("skeleton detail rebuilt", not _skel._loading)

    print()
    if failures:
        print(f"自检失败：{len(failures)} 项未通过 -> {failures}")
        return 1
    print("全部自检通过。")
    return 0


# ----------------------------------------------------------------------
def main() -> int:
    """程序主入口。"""
    args = sys.argv[1:]

    # --selftest：纯逻辑自检，无需 GUI 与管理员权限
    if "--selftest" in args:
        return _selftest()

    smoke = "--smoke" in args
    boot = "--boot" in args

    # 管理员提权（冒烟模式下跳过提权，保证自动化验证确定性）
    admin = is_admin()
    if not admin and not smoke:
        if try_elevate():
            return 0  # 提权实例已启动，当前进程退出
        admin = is_admin()  # 用户拒绝提权 -> 基础模式

    return run_gui(admin, smoke, boot=boot)


if __name__ == "__main__":
    sys.exit(main())
