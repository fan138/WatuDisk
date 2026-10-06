# -*- coding: utf-8 -*-
"""v1.2 报告与界面细节优化回归测试。

对应用户 2026-10-05 22:42 的四点要求：

1. 导出报告要包含盘面扫描结果（最近一次），并做好页面美化；
2. 报告要有 GitHub 链接与建议反馈链接，做得低调但不缺；
3. **反馈地址必须是 https://github.com/fan138/WatuDisk/issues**
   （此前「去 GitHub 提建议」按钮错链到仓库首页，等于没接住反馈）；
4. 盘面扫描按钮名与文案可读性；
5. 体检记录展开时会遮挡卡片详情——展开卡片前应自动收起记录。

另含一条硬约束：报告与弹窗的对外文案不得出现单一论坛名（多论坛策略）。
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

import core.store as store_module  # noqa: E402
from core import report  # noqa: E402
from core.store import Store  # noqa: E402

SRC_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
UI_PATH = os.path.join(SRC_ROOT, "ui", "main_window.py")
with open(UI_PATH, "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()

# 用户指定的正确反馈地址
ISSUES_URL = "https://github.com/fan138/WatuDisk/issues"
REPO_URL = "https://github.com/fan138/WatuDisk"


def _with_scan_records(records: dict) -> object:
    """建一个临时 store（注入 surface_scans），返回它；用完由调用方还原。"""
    previous = store_module._store
    temp_dir = tempfile.mkdtemp(prefix="watudisk_scan_")
    store = Store(dir_override=temp_dir)
    for device_id, payload in records.items():
        store.save_surface_scan(device_id, payload)
    store_module._store = store
    return previous


def _results(devices=("0", "1")) -> list[dict]:
    return [
        {
            "model": f"测试盘{dev}",
            "device_id": dev,
            "bus_type": "NVME",
            "media_type": "SSD",
            "is_ssd": True,
            "size": 1000204886016,
            "health_score": 95,
            "grade": "优秀",
            "smart_status": "OK",
            "power_on_hours": 500,
            "temperature": 40,
            "metrics": [],
            "reasons": ["各项指标正常"],
            "suggestions": [],
        }
        for dev in devices
    ]


# ---------------- 1. 报告要含盘面扫描结果 ----------------

def test_report_shows_surface_scan_section_when_scanned():
    """扫过的盘，报告里必须有「盘面扫描」卡片——否则等于扫了白扫。"""
    prev = _with_scan_records({
        "0": {"model": "金士顿SV300S37A240G", "mode": "quick", "chunks_ok": 512,
              "chunks_failed": 0, "bytes_scanned": 2147483648,
              "elapsed_sec": 1.02, "speed_mb_s": 2005.3},
    })
    try:
        html = report.build_report_html(_results(("0",)), version="v1.2.0")
    finally:
        store_module._store = prev
    assert "盘面扫描（最近一次）" in html, "报告缺少盘面扫描结果卡片"
    assert "金士顿SV300S37A240G" in html, "扫描卡片应显示盘型号"


def test_report_omits_scan_section_when_never_scanned():
    """没扫过的盘不应出现空卡片——避免「看起来扫过其实没扫」的误导。"""
    prev = _with_scan_records({})
    try:
        html = report.build_report_html(_results(("0",)), version="v1.2.0")
    finally:
        store_module._store = prev
    assert "盘面扫描（最近一次）" not in html, "未扫描过却显示扫描卡片"


def test_scan_section_distinguishes_quick_and_full():
    """抽样与全盘必须如实区分标注，不能都写成一样的结论。"""
    prev = _with_scan_records({
        "0": {"model": "抽样盘", "mode": "quick", "chunks_ok": 512,
              "chunks_failed": 0, "bytes_scanned": 2147483648,
              "elapsed_sec": 1.0, "speed_mb_s": 2000.0},
        "1": {"model": "全盘盘", "mode": "full", "chunks_ok": 900,
              "chunks_failed": 0, "bytes_scanned": 1000204886016,
              "elapsed_sec": 500.0, "speed_mb_s": 1900.0},
    })
    try:
        html = report.build_report_html(_results(("0", "1")), version="v1.2.0")
    finally:
        store_module._store = prev
    assert "抽样" in html, "抽样档未标注"
    assert "全盘逐块" in html, "全盘档未标注"


def test_scan_section_shows_failure_with_warning_color():
    """有读失败时要有警示色与失败块数，不能轻描淡写。"""
    prev = _with_scan_records({
        "0": {"model": "坏道盘", "mode": "full", "chunks_ok": 900,
              "chunks_failed": 23, "bytes_scanned": 1000204886016,
              "elapsed_sec": 500.0, "speed_mb_s": 1900.0},
    })
    try:
        html = report.build_report_html(_results(("0",)), version="v1.2.0")
    finally:
        store_module._store = prev
    assert "多处读失败" in html, "多处失败未如实标注"
    assert "scan-bad" in html, "多处失败未用危险色"
    assert "23" in html, "未显示失败块数"


def test_scan_section_warns_sample_may_miss():
    """抽样可能漏掉局部坏道，报告里必须如实提醒，不能让人当成全盘结论。"""
    prev = _with_scan_records({
        "0": {"model": "抽样盘", "mode": "quick", "chunks_ok": 512,
              "chunks_failed": 0, "bytes_scanned": 2147483648,
              "elapsed_sec": 1.0, "speed_mb_s": 2000.0},
    })
    try:
        html = report.build_report_html(_results(("0",)), version="v1.2.0")
    finally:
        store_module._store = prev
    block = html[html.index("盘面扫描（最近一次）") :][:1200]
    assert "抽样" in block, "缺少抽样说明"
    assert "漏" in block or "不代表 100% 无故障" in block, "未提醒抽样可能漏检"


def test_scan_section_never_says_good_after_abort():
    """中止的扫描不该被写成「未发现读失败」——store 只存 finished 记录，测试守住这条。"""
    prev = _with_scan_records({})
    try:
        store = store_module._store
        store.save_surface_scan("0", {
            "model": "中止盘", "mode": "full", "chunks_ok": 100, "chunks_failed": 0,
            "bytes_scanned": 419430400, "elapsed_sec": 60.0, "speed_mb_s": 6.9,
            "cancelled": True, "finished": False,
        })
        html = report.build_report_html(_results(("0",)), version="v1.2.0")
    finally:
        store_module._store = prev
    # 即便记录里带cancelled，报告也不得把它说成「未发现读失败」
    assert "未发现读失败" not in html or "中止" in html, "中止的扫描被误报为无故障"


# ---------------- 2 & 3. GitHub 链接与反馈地址 ----------------

def test_report_contains_repo_and_issues_links():
    """报告页脚要同时有仓库地址与反馈地址。"""
    html = report.build_report_html(_results(("0",)), version="v1.2.0")
    assert REPO_URL in html, "报告缺少项目地址"
    assert ISSUES_URL in html, "报告缺少建议反馈地址"


def test_report_links_are_clickable_anchor():
    """必须是真链接（<a href>），不是纯文字——用户要能直接点开。"""
    html = report.build_report_html(_results(("0",)), version="v1.2.0")
    assert f"href='{ISSUES_URL}'" in html or f'href="{ISSUES_URL}"' in html, \
        "反馈地址不是可点击链接"
    assert f"href='{REPO_URL}'" in html or f'href="{REPO_URL}"' in html, \
        "项目地址不是可点击链接"


def test_report_links_are_lowkey_not_loud():
    """用户要求「不那么张扬」：页脚链接不能是大按钮或高饱和色。"""
    html = report.build_report_html(_results(("0",)), version="v1.2.0")
    footer_start = html.index("class='footer'")
    footer = html[footer_start:]
    for loud in ("<button", "background:#2563EB", "background: #2563EB"):
        assert loud not in footer, f"页脚出现张扬样式：{loud}"


def test_issues_url_constant_is_correct():
    """反馈地址常量必须是 Issues 页，不能是仓库首页。"""
    assert report.GITHUB_ISSUES_URL == ISSUES_URL, \
        f"反馈地址错误：{report.GITHUB_ISSUES_URL}"


def test_ui_feedback_button_goes_to_issues_not_home():
    """「去 GitHub 提建议」按钮必须跳 Issues 页。

    这正是用户指出的问题：按钮写「提建议」却跳到仓库首页，等于没接住反馈。
    """
    assert "GITHUB_ISSUES_URL" in UI_SRC, "界面未定义 Issues 反馈地址"
    help_start = UI_SRC.index("def _show_help_center")
    help_end = UI_SRC.index("def _build_ui", help_start)
    help_body = UI_SRC[help_start:help_end]
    assert "GITHUB_ISSUES_URL" in help_body, "「去 GitHub 提建议」按钮仍指向仓库首页"
    # 底部「GitHub」按钮（看源码）可以继续用首页，两者用途不同
    assert "GITHUB_URL)" in UI_SRC, "底部 GitHub 按钮应仍指向仓库首页"


def test_ui_help_text_shows_issues_address():
    """弹窗正文里也要能看到反馈地址，用户不必猜去哪里提。"""
    help_start = UI_SRC.index("def _show_help_center")
    help_end = UI_SRC.index("def _build_ui", help_start)
    assert "Issue" in UI_SRC[help_start:help_end] or "提建议" in UI_SRC[help_start:help_end], \
        "弹窗未提示反馈渠道"


# ---------------- 4. 按钮命名 ----------------

def test_scan_button_has_meaningful_label():
    """盘面扫描按钮名要让坛友一看就懂在做什么。"""
    match = re.search(r'QPushButton\("([^"]+)"\)\s*\n\s*self\._virscan_btn', UI_SRC)
    assert match, "未找到盘面扫描按钮"
    label = match.group(1)
    assert label, "按钮文字为空"
    assert len(label) <= 6, f"按钮名过长（{len(label)} 字）：{label}"


# ---------------- 5. 体检记录不得遮挡卡片详情 ----------------

def test_history_panel_has_collapse_api():
    """记录面板要提供「自动收起」能力，供展开卡片时调用。"""
    assert "def collapse_if_expanded" in UI_SRC, "HistoryPanel 缺少 collapse_if_expanded 方法"


def test_disk_card_collapses_history_before_expanding():
    """展开卡片前必须先收起记录——否则详情被整块遮住，点开像没反应。"""
    card_start = UI_SRC.index("class DiskCard")
    card_end = UI_SRC.index("class MainWindow")
    card = UI_SRC[card_start:card_end]
    assert "_collapse_history_below" in card, "DiskCard 未实现收起记录的逻辑"
    press_start = card.index("def mousePressEvent")
    press_body = card[press_start : press_start + 700]
    # 顺序：先收起记录，再展开详情
    assert press_body.index("_collapse_history_below") < press_body.index("setVisible(expanding)"), \
        "必须先收起体检记录再展开详情"


def test_collapse_history_is_failure_tolerant():
    """找不到记录面板时静默跳过，不能因此让点击卡片报错。"""
    card_start = UI_SRC.index("class DiskCard")
    card_end = UI_SRC.index("class MainWindow")
    card = UI_SRC[card_start:card_end]
    fn_start = card.index("def _collapse_history_below")
    body = card[fn_start : fn_start + 900]
    assert "while node is not None" in body, "未沿 parent 链查找"
    assert "return" in body.split("while")[0] or "isinstance(panel, HistoryPanel)" in body, \
        "未做类型判断，误命中会崩"


def test_collapse_only_when_expanding():
    """收起动作只在「即将展开」时做：收起卡片不该动记录（用户可能想对照着看）。"""
    card_start = UI_SRC.index("class DiskCard")
    card_end = UI_SRC.index("class MainWindow")
    card = UI_SRC[card_start:card_end]
    press_start = card.index("def mousePressEvent")
    press_body = card[press_start : press_start + 700]
    assert "if expanding:" in press_body, "收起动作未受「即将展开」条件保护"


def test_collapse_persists_setting():
    """自动收起要同步存回设置，否则下次打开又自动展开，用户会觉得莫名其妙。"""
    panel_start = UI_SRC.index("class HistoryPanel")
    panel_end = UI_SRC.index("class DiskCard")
    panel = UI_SRC[panel_start:panel_end]
    fn_start = panel.index("def collapse_if_expanded")
    body = panel[fn_start : fn_start + 800]
    assert "set_setting" in body, "自动收起未持久化，下次启动会复发"


# ---------------- 通用：对外文案 ----------------

def test_no_forum_name_in_report_or_dialog():
    """多论坛策略：报告与弹窗都不得出现单一论坛名。"""
    html = report.build_report_html(_results(("0",)), version="v1.2.0")
    assert not re.search(r"52\s*pojie|吾爱破解", html, re.IGNORECASE), "报告出现论坛名"
    help_start = UI_SRC.index("def _show_help_center")
    help_end = UI_SRC.index("def _build_ui", help_start)
    assert not re.search(r"52\s*pojie|吾爱破解", UI_SRC[help_start:help_end], re.IGNORECASE), \
        "弹窗出现论坛名"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))