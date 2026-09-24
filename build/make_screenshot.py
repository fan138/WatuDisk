# -*- coding: utf-8 -*-
"""离线渲染主界面截图，仅用于生成 README 配图。

不写盘（除输出 png）、不联网；用 Qt 离屏平台渲染主窗口并注入
示例硬盘数据，抓取后保存为仓库根目录 preview.png。
"""
import os
import sys

# 脚本位于 <repo>/build/ 下，仓库根目录即其上一级
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 让脚本能 import src 下的包
sys.path.insert(0, os.path.join(_ROOT, "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

import core.store as _store_mod
import tempfile as _tempfile

# 使用临时目录的存储，避免生成截图时向用户真实的 %APPDATA%\WatuDiskSprite 写入数据
_tmp_store_dir = _tempfile.TemporaryDirectory()
_orig_get_store = _store_mod.get_store


def _patched_get_store():
    return _store_mod.Store(dir_override=_tmp_store_dir.name)


_store_mod.get_store = _patched_get_store

import core.verdict as verdict  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def _load_cjk_font(app: QApplication) -> None:
    """离屏渲染默认无中文字体，手动注册微软雅黑 / 黑体，并用 Segoe UI Symbol 兜底几何符号。"""
    families: list[str] = []
    for font_file in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\seguisym.ttf",
    ):
        if not os.path.exists(font_file):
            continue
        fid = QFontDatabase.addApplicationFont(font_file)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
        families.extend(fams)
    if families:
        font = QFont()
        font.setFamilies(families)  # Qt6：多字体族回退（缺字形自动跳到下一个）
        font.setPointSize(9)
        app.setFont(font)
        print(f"[screenshot] loaded fonts: {families}")


def make_disk(device_id, model, media, bus, size, health, counters, nvme, attrs, events, volumes):
    """构造一份与 DiskCard 完全兼容的示例检测结果。"""
    disk = {
        "device_id": device_id,
        "model": model,
        "media_type": media,
        "bus_type": bus,
        "health_status": health,
        "op_status": "OK",
        "size": size,
        "serial": "SAMPLE" + device_id,
    }
    v = verdict.evaluate_disk(
        disk, counters, attrs, len(events), events,
        [vol for vol in volumes if vol.get("dirty")], nvme,
    )
    return {
        "disk": disk,
        "counters": counters,
        "nvme_health": nvme,
        "smart_attrs": attrs,
        "event_count": len(events),
        "event_recent": events,
        "dirty_volumes": [vol for vol in volumes if vol.get("dirty")],
        "all_volumes": volumes,
        "verdict": v,
    }


def sample_results():
    # 盘 0：系统 NVMe，健康
    nvme0 = {
        "critical_warning": 0, "temperature_c": 36, "available_spare_pct": 100,
        "spare_threshold": 10, "percentage_used": 2,
        "data_units_read": 123456, "data_units_written": 234567,
        "power_cycles": 1072, "power_on_hours": 13296,
        "unsafe_shutdowns": 88, "media_errors": 0, "error_log_entries": 0,
    }
    disk0 = make_disk(
        "0", "WD Black SN770 1TB", "SSD", "NVMe", 1 * 1024 ** 4, "Healthy",
        {"Temperature": 38, "Wear": 3, "PowerOnHours": 13296},
        nvme0, [], [],
        [{"drive": "C:", "dirty": False, "disk_number": 0, "free_pct": 62,
          "free": 620 * 1024 ** 3, "size": 1000 * 1024 ** 3}],
    )

    # 盘 1：SATA 固态，温度升高 + 寿命偏低 + 一条待映射扇区（红色高亮）
    attrs1 = [
        {"id": 0x05, "hex": "05", "name": "重映射扇区数", "value": 100, "raw": 0},
        {"id": 0x09, "hex": "09", "name": "通电时间", "value": 95, "raw": 20500},
        {"id": 0xC5, "hex": "C5", "name": "待映射扇区数", "value": 98, "raw": 2},
        {"id": 0xC7, "hex": "C7", "name": "UltraDMA CRC 错误", "value": 200, "raw": 0},
    ]
    disk1 = make_disk(
        "1", "Samsung 870 EVO 500GB", "SSD", "SATA", 500 * 1024 ** 3, "Warning",
        {"Temperature": 58, "Wear": 78, "PowerOnHours": 20500},
        None, attrs1, [],
        [{"drive": "D:", "dirty": False, "disk_number": 1, "free_pct": 41,
          "free": 205 * 1024 ** 3, "size": 500 * 1024 ** 3}],
    )

    # 盘 2：机械盘，剩余空间告急（红色）
    disk2 = make_disk(
        "2", "Seagate BarraCuda 2TB", "HDD", "SATA", 2 * 1024 ** 4, "Healthy",
        {"Temperature": 41, "PowerOnHours": 31000},
        None, [], [],
        [{"drive": "E:", "dirty": False, "disk_number": 2, "free_pct": 4,
          "free": 80 * 1024 ** 3, "size": 2000 * 1024 ** 3}],
    )

    # 盘 3：大容量机械盘，健康
    disk3 = make_disk(
        "3", "TOSHIBA MG08ACA16TE 16TB", "HDD", "SATA", 16 * 1024 ** 4, "Healthy",
        {"Temperature": 37, "PowerOnHours": 8600},
        None,
        [
            {"id": 0x05, "hex": "05", "name": "重映射扇区数", "value": 100, "raw": 0},
            {"id": 0x09, "hex": "09", "name": "通电时间", "value": 99, "raw": 8600},
        ],
        [],
        [{"drive": "F:", "dirty": False, "disk_number": 3, "free_pct": 55,
          "free": 9000 * 1024 ** 3, "size": 16000 * 1024 ** 3}],
    )

    # 盘 4：移动固态盘，健康
    nvme4 = {
        "critical_warning": 0, "temperature_c": 34, "available_spare_pct": 100,
        "spare_threshold": 10, "percentage_used": 5,
        "data_units_read": 45678, "data_units_written": 78901,
        "power_cycles": 320, "power_on_hours": 1120,
        "unsafe_shutdowns": 12, "media_errors": 0, "error_log_entries": 0,
    }
    disk4 = make_disk(
        "4", "Kingston A2000 1TB", "SSD", "NVMe", 1 * 1024 ** 4, "Healthy",
        {"Temperature": 34, "Wear": 5, "PowerOnHours": 1120},
        nvme4, [], [],
        [{"drive": "G:", "dirty": False, "disk_number": 4, "free_pct": 71,
          "free": 710 * 1024 ** 3, "size": 1000 * 1024 ** 3}],
    )
    return [disk0, disk1, disk2, disk3, disk4]


def main() -> int:
    # 阻止自动检测（避免真实 PowerShell / 管理员依赖），改为注入示例数据
    MainWindow._start_detection = lambda self, source="手动体检": None  # noqa: ARG005

    app = QApplication(sys.argv)
    app.setStyleSheet("")  # 由 MainWindow 内部设置 QSS
    _load_cjk_font(app)

    # 预置两条体检记录，让截图更真实（写入临时存储，不影响用户数据）
    st = _store_mod.get_store()
    st.set_setting("history_expanded", False)
    st.append_history({"time": "2026-09-24 09:12", "level": "ok",
                       "text": "全部健康（3 块盘，1.2 秒）", "source": "开机体检"})
    st.append_history({"time": "2026-09-23 21:35", "level": "warning",
                       "text": "1 块盘需要关注（共 3 块，1.4 秒）", "source": "定时体检"})

    window = MainWindow(admin=True, version="v1.0.0", enable_tray=False)
    window.setWindowTitle("挖兔硬盘精灵 v1.0.0")

    # 截图专用：离屏字体缺少小三角字形，记录区展开按钮改为纯文字，避免出现方块
    try:
        window._history_panel._toggle_btn.setText("展开")
    except Exception:
        pass

    results = sample_results()
    window._results = results
    window._populate_cards(results)

    summary = verdict.summarize(results)
    window._ov_total.setText(str(summary["total"]))
    window._ov_healthy.setText(str(summary["healthy"]))
    window._ov_bad.setText(str(summary["warning"] + summary["danger"]))
    window._stage_label.setText("检测完成 · 用时 1.2 秒")
    window._btn_detect.setEnabled(True)
    window._btn_detect.setText("重新检测")
    window._btn_export.setEnabled(True)

    # 收紧窗口高度，让内容刚好填满
    window.resize(980, 622)
    window.show()
    app.processEvents()

    out_path = os.path.join(_ROOT, "preview.png")

    def grab_and_save() -> None:
        pix = window.centralWidget().grab()
        pix.save(out_path)
        print(f"[screenshot] saved -> {out_path} ({pix.width()}x{pix.height()})")
        app.quit()

    QTimer.singleShot(2200, grab_and_save)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
