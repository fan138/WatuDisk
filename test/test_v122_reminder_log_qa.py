# -*- coding: utf-8 -*-
"""v1.2.2「提醒记录 + 防打扰冷却」回归测试。

用户反馈原话：高强度使用电脑时软件弹了张「有点热」的卡片，弹出后就消失了，
「有一定的风险提醒的时候，这些提醒记录在哪里继续查看，还要考虑避免大量
无效的信息干扰」。

本版闭环三件事：
1. **记下来**：异常级气泡（warn/danger）经 tray.notify_custom 统一收口，
   静默写入 store.notify_log()（有界 200 条，info 级不记——健康/完成类
   记了只会把真正的提醒挤出去），主界面「提醒记录」面板随时回看，
   每条附关键数字（最高温 / 最紧空间 / 需关注盘数）；
2. **不轰炸**：同类异常提醒 4 小时冷却（notify_policy.should_notify_worse），
   按分类各自计时；危险级豁免（永远忠言逆耳）；总开关优先；
3. **找得到**：点 warn/danger 气泡 = 唤起主窗口 + 展开提醒记录面板。

顺带修复：store.notify_log 自 v1.0 起就是死代码——只往内存里追加、
_load 从不读回，重启后记录全丢。本测试第 3 条守这个持久化修复。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

import core.store as store_mod  # noqa: E402
from core import notify_policy  # noqa: E402
from core.store import MAX_HISTORY, Store  # noqa: E402

_UI_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "ui"))
with open(os.path.join(_UI_PATH, "main_window.py"), "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()
with open(os.path.join(_UI_PATH, "tray.py"), "r", encoding="utf-8") as _fh:
    TRAY_SRC = _fh.read()

# 帮助弹窗方法体（与 test_v12_score_explain_qa 同一取法）
_HELP_START = UI_SRC.index("def _show_help_center")
HELP_BODY = UI_SRC[_HELP_START:UI_SRC.index("def _build_ui", _HELP_START)]


def _make_store() -> tuple[Store, str]:
    tmp = tempfile.mkdtemp(prefix="diskguard_test_reminder_")
    return Store(tmp), tmp


def _use_temp_store() -> Store:
    """把 notify_policy 看到的单例换到临时目录（用完由调用方复位）。"""
    store, _tmp = _make_store()
    store_mod._store = store
    return store


def _reset_store() -> None:
    store_mod._store = None


def _entry(i: int, level: str = "warn") -> dict:
    return {
        "time": f"2026-10-18 20:{i:02d}",
        "level": level,
        "title": "温度关怀",
        "text": f"测试文案 {i}",
        "source": "定时体检",
        "context": {"最高温": f"{60 + i}°C"},
    }


# ---------------- store 层：提醒记录持久化 ----------------

def test_notify_log_appends_newest_first():
    """新记录插在最前，字段原样保留（面板按新在前渲染）。"""
    store, tmp = _make_store()
    try:
        for i in range(3):
            store.append_notify_log(_entry(i))
        log = store.notify_log()
        assert len(log) == 3
        assert log[0]["text"] == "测试文案 2", "最新一条应在最前"
        assert log[0]["context"] == {"最高温": "62°C"}, "关键数字应随记录保留"
        assert log[0]["source"] == "定时体检", "来源应随记录保留"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_notify_log_bounded_at_max_history():
    """有界封顶：超出自动淘汰最旧，体积不随使用时间无限增长。"""
    store, tmp = _make_store()
    try:
        for i in range(MAX_HISTORY + 5):
            store.append_notify_log(_entry(i % 60))
        log = store.notify_log()
        assert len(log) == MAX_HISTORY, f"应封顶 {MAX_HISTORY} 条，实际 {len(log)}"
        assert log[0]["text"] == f"测试文案 {(MAX_HISTORY + 4) % 60}", "淘汰后最新一条仍在最前"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_notify_log_persists_across_reload():
    """持久化修复守卫：v1.0 起 notify_log 只写内存、_load 从不读回，
    重启后提醒记录全丢。新 Store 实例（同目录）必须能读回已写的记录。"""
    store, tmp = _make_store()
    try:
        store.append_notify_log(_entry(1))
        reloaded = Store(tmp)
        log = reloaded.notify_log()
        assert len(log) == 1, "重启后提醒记录丢失（_load 未读回 notify_log）"
        assert log[0]["title"] == "温度关怀"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------- 冷却层：同类异常 4 小时不重复 ----------------

def test_cooldown_blocks_repeat_within_window():
    """同类异常：刚弹过，4 小时内再判应拦截（用户说的「无效信息干扰」）。"""
    store = _use_temp_store()
    try:
        assert notify_policy.should_notify_worse("gentle", "hot") is True, "首次应放行"
        notify_policy.mark_worse_notified("hot")
        assert notify_policy.should_notify_worse("gentle", "hot") is False, "冷却期内应拦截"
    finally:
        _reset_store()


def test_cooldown_allows_after_window():
    """超过 4 小时冷却自动解除（不是永久静默）。"""
    store = _use_temp_store()
    try:
        past = (datetime.now() - timedelta(hours=5)).isoformat(timespec="seconds")
        store.set_setting("notify_worse_last_hot", past)
        assert notify_policy.should_notify_worse("gentle", "hot") is True, "超窗应放行"
    finally:
        _reset_store()


def test_danger_exempt_from_cooldown():
    """危险级豁免冷却——永远忠言逆耳，绝不因「最近提醒过」而沉默。"""
    store = _use_temp_store()
    try:
        notify_policy.mark_worse_notified("danger")
        assert notify_policy.should_notify_worse("gentle", "danger") is True, "危险不得被冷却拦"
    finally:
        _reset_store()


def test_categories_have_independent_cooldowns():
    """按分类各自计时：高温冷却中，空间类提醒不受影响。"""
    store = _use_temp_store()
    try:
        notify_policy.mark_worse_notified("hot")
        assert notify_policy.should_notify_worse("gentle", "warn") is True, "不同分类不应互相锁定"
        assert notify_policy.should_notify_worse("gentle", "space_low") is True, "不同分类不应互相锁定"
    finally:
        _reset_store()


def test_master_switch_silences_everything():
    """总开关（notify_enabled）关闭时一切静默，危险也不例外。"""
    store = _use_temp_store()
    try:
        store.set_setting("notify_enabled", False)
        assert notify_policy.should_notify_worse("gentle", "danger") is False, "总开关应压过危险豁免"
        assert notify_policy.should_notify_worse("gentle", "hot") is False
    finally:
        _reset_store()


def test_dirty_timestamp_does_not_lock_forever():
    """脏数据（非时间串）不该把提醒永久锁死——解析失败按放行处理。"""
    store = _use_temp_store()
    try:
        store.set_setting("notify_worse_last_hot", "not-a-timestamp")
        assert notify_policy.should_notify_worse("gentle", "hot") is True, "脏数据应放行而非永久静默"
    finally:
        _reset_store()


def test_healthy_path_unaffected_by_cooldown_refactor():
    """健康类提示的上限与习惯识别不回归（冷却只作用于异常类）。"""
    store = _use_temp_store()
    try:
        assert notify_policy.should_notify_healthy("gentle") is True, "首条健康提示应放行"
        notify_policy.mark_healthy_notified("gentle")
        notify_policy.mark_healthy_notified("gentle")
        assert notify_policy.should_notify_healthy("gentle") is False, "gentle 每日 2 条上限应仍在"
    finally:
        _reset_store()


# ---------------- 功能层：面板真构造（源码守卫抓不到运行时才炸的问题） ----------------

def test_health_record_panel_merges_both_tabs():
    """真构造「健康记录」卡片：默认体检标签、可切提醒、计数与角标同步。

    v1.2.2 用户要求：两张卡片（体检记录 / 提醒记录）合并为一个「健康记录」，
    点开是两个标签，默认体检记录。这条守合并后的运行时行为——
    源码守卫守不住「默认标签选错」「计数不刷新」这类逻辑问题。
    """
    from PySide6.QtWidgets import QApplication

    from ui.main_window import HealthRecordPanel

    app = QApplication.instance() or QApplication([])  # noqa: F841 - 需持引用
    store = _use_temp_store()
    try:
        panel = HealthRecordPanel()
        # 默认标签 = 体检记录（stack 第 0 页），折叠态随设置
        assert panel._stack.currentIndex() == 0, "默认标签应为体检记录"
        assert panel._tab == "history", "默认 tab 状态应为 history"
        assert panel._count_label.text() == "体检 0 次 · 提醒 0 条", \
            f"空态汇总计数不对: {panel._count_label.text()}"

        # 写入两类记录 -> 汇总计数与标签角标都要跟上
        store.append_history({"time": "2026-10-18 20:00", "level": "ok", "text": "一切正常"})
        store.append_history({"time": "2026-10-18 19:00", "level": "ok", "text": "一切正常"})
        store.append_notify_log(_entry(1))
        panel.refresh()
        assert panel._count_label.text() == "体检 2 次 · 提醒 1 条", \
            f"汇总计数未同步: {panel._count_label.text()}"
        assert panel._tab_history_btn.text() == "体检记录 2", "体检标签缺条数角标"
        assert panel._tab_reminder_btn.text() == "提醒记录 1", "提醒标签缺条数角标"

        # 切到提醒标签：stack 翻页 + 状态持久化
        panel._switch_tab("reminder")
        assert panel._stack.currentIndex() == 1, "切换后应显示提醒记录内容"
        assert store.get_setting("health_tab") == "reminder", "当前标签未持久化"

        # 展开 / 收起往返（默认折叠）
        assert panel.collapse_if_expanded() is False, "默认折叠不应报「做了收起」"
        panel._on_toggle()
        assert panel._expanded is True and store.get_setting("health_expanded") is True, \
            "展开态应记录并持久化"
        assert panel.collapse_if_expanded() is True, "展开态应能收起"
        assert panel._expanded is False

        # 气泡直达：展开 + 自动切到提醒标签
        panel.expand_and_reveal()
        assert panel._expanded is True, "expand_and_reveal 应展开卡片"
        assert panel._tab == "reminder", "expand_and_reveal 应切到提醒记录标签"

        # slim 子面板：无自有头部 / 恒展开 / 折叠开关已交由外层
        inner = panel.history_panel
        assert inner._embedded is True and inner._expanded is True, "slim 子面板应恒展开"
        inner._on_toggle()
        assert inner._expanded is True, "slim 子面板的折叠开关应已失效（外层统一管理）"
        assert inner.collapse_if_expanded() is False, "slim 子面板不应自行收起"
    finally:
        _reset_store()


def test_reminder_panel_constructs_and_roundtrips():
    """真构造 ReminderPanel 并走一遍 渲染/展开/收起。

    为什么要有这条：v1.2.2 开发时把滚动条策略枚举写成 ScrollAlwaysOff
    （少一个 Bar），17 条源码守卫全绿、selftest 也绿，直到 main.py --smoke
    才炸。源码守卫守「代码里有某段文本」，守不住「枚举名拼错」——
    这类问题只有真把控件造出来才会暴露。
    """
    from PySide6.QtWidgets import QApplication

    from ui.main_window import ReminderPanel

    app = QApplication.instance() or QApplication([])  # noqa: F841 - 需持引用
    store = _use_temp_store()
    try:
        panel = ReminderPanel()
        assert panel._count_label.text() == "共 0 条", "空态计数应为 0"

        store.append_notify_log(_entry(1, level="danger"))
        store.append_notify_log(_entry(2))
        panel.refresh()
        assert panel._count_label.text() == "共 2 条", "刷新后计数应跟上"

        # 展开 / 收起往返（默认折叠，expand_and_reveal 应能展开并记住状态）
        assert panel.collapse_if_expanded() is False, "默认折叠不应报「做了收起」"
        panel.expand_and_reveal()
        assert panel._expanded is True, "expand_and_reveal 应展开"
        assert store.get_setting("reminder_expanded") is True, "展开状态应持久化"
        assert panel.collapse_if_expanded() is True, "展开态应能收起"
        assert panel._expanded is False

        # 行文本：级别图标 + 时间 + 标题：文案 + 来源
        row = ReminderPanel._row_text(_entry(1, level="danger"))
        assert "✗" in row and "温度关怀" in row and "[定时体检]" in row, f"行文本缺要素: {row}"
    finally:
        _reset_store()


# ---------------- 接线层：统一收口（源码守卫） ----------------

def test_tray_records_abnormal_toasts_only():
    """notify_custom 是唯一出口：异常级才写记录，info 级不记。"""
    assert "append_notify_log" in TRAY_SRC, "notify_custom 未接入提醒记录"
    assert 'if level != "info":' in TRAY_SRC, "缺少「仅异常级记录」的守卫"


def test_tray_bg_check_applies_cooldown():
    """后台定时检测（重复提醒的高发路径）必须走冷却 + 计时。"""
    assert "should_notify_worse" in TRAY_SRC, "后台检测未接冷却"
    assert "mark_worse_notified" in TRAY_SRC, "弹出后未记冷却起点"


def test_tray_passes_context_and_source():
    """记录要带关键数字与来源，否则回看时只剩一句诗情文案。"""
    assert "context=context" in TRAY_SRC and 'source="定时体检"' in TRAY_SRC, \
        "后台检测未传 context/source"


def test_ui_has_reminder_panel():
    """主界面要有「提醒记录」面板：数据源 notify_log + 展开定位能力。

    v1.2.2：体检 / 提醒已合并为「健康记录」卡片（标签页切换），这里同时守
    合并结构——卡片在、两个 slim 子面板在、主窗口只挂一张卡片。
    """
    assert "class ReminderPanel" in UI_SRC, "缺少 ReminderPanel"
    assert "notify_log()" in UI_SRC, "面板未接 notify_log 数据源"
    assert "def expand_and_reveal" in UI_SRC, "缺少展开定位方法"
    assert "提醒记录" in UI_SRC, "界面缺少「提醒记录」字样"
    # 合并为「健康记录」标签卡片
    assert "class HealthRecordPanel" in UI_SRC, "缺少健康记录卡片（合并容器）"
    assert "健康记录" in UI_SRC, "界面缺少「健康记录」字样"
    assert "QStackedWidget()" in UI_SRC, "健康记录未用 StackedWidget 托管两个标签页"
    assert "HistoryPanel(embedded=True)" in UI_SRC, "体检记录未以 slim 模式内嵌"
    assert "ReminderPanel(embedded=True)" in UI_SRC, "提醒记录未以 slim 模式内嵌"
    assert "self._health_panel = HealthRecordPanel()" in UI_SRC, \
        "主窗口未挂载健康记录卡片"
    assert UI_SRC.count("root.addWidget(self._history_panel)") == 0, \
        "合并后主窗口不应再单独挂体检记录卡片"
    assert UI_SRC.count("root.addWidget(self._reminder_panel)") == 0, \
        "合并后主窗口不应再单独挂提醒记录卡片"


def test_toast_click_opens_reminder_panel():
    """点 warn/danger 气泡直达记录（用户核心诉求：看完能找回）。"""
    assert "wake_up_and_show_reminders" in UI_SRC, "主窗口缺少直达方法"
    assert "wake_up_and_show_reminders" in TRAY_SRC, "气泡点击未接直达方法"
    # 合并后直达 = 展开健康记录并切到提醒标签
    assert 'self._switch_tab("reminder")' in UI_SRC or "_switch_tab(\"reminder\")" in UI_SRC, \
        "直达未切到提醒记录标签"


def test_card_expansion_collapses_reminder_panel():
    """展开磁盘卡片前也要收起提醒记录（与体检记录同一占位逻辑）。

    v1.2.2：合并为「健康记录」卡片后，收起链优先命中外层卡片。
    """
    card_start = UI_SRC.index("class DiskCard")
    card_end = UI_SRC.index("class MainWindow")
    card = UI_SRC[card_start:card_end]
    fn_start = card.index("def _collapse_history_below")
    fn_body = card[fn_start:]
    assert 'getattr(node, "_health_panel"' in fn_body, "展开卡片未优先收起健康记录卡片，详情会被遮住"
    assert 'getattr(node, "_reminder_panel"' in fn_body, "展开卡片未收起提醒记录，详情会被遮住"
    # 优先级：外层卡片必须先于旧分支命中（取代码行，避免被 docstring 字样干扰）
    health_at = fn_body.index('getattr(node, "_health_panel"')
    reminder_at = fn_body.index('getattr(node, "_reminder_panel"')
    assert health_at < reminder_at, "收起链应优先命中健康记录卡片"


def test_help_lists_reminder_record():
    """「?」弹窗本版更新清单要如实写这条（对外承诺与实物一致）。"""
    assert "提醒记录" in HELP_BODY, "帮助弹窗未提「提醒记录」"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
