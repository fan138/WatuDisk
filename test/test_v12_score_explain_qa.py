# -*- coding: utf-8 -*-
"""v1.2（#5）健康分口径说明回归测试。

坛友反馈：挖兔打 92 分，HardDiskSentinel 打 78 分，「到底谁准？是不是不准？」
这类误解会直接损伤口碑，而且光在文档里解释没人看得到——必须让人在
软件里随时能就地看到「读数一致、算法不同，分数不同属正常」。

**v1.2 定稿形态（2026-10-05 用户调整）**：
原先底部挂了一个独立的「评分说明」按钮，v1.2 收口时用户要求把它的内容
并入右下角「?」使用说明弹窗，底部按钮更干净。因此断言锁定的是：
- 右下角「?」入口存在，且连到使用说明弹窗；
- 弹窗里必须含健康分口径的三段核心论点；
- 弹窗里必须含「本版已更新内容」与「下一版计划」；
- **不得再出现「v1.2 开发中」这类自相矛盾措辞**（软件本体已是 v1.2）；
- 报告层仍保留同样口径的说明卡片（两处说法必须一致）。
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import report  # noqa: E402

UI_PATH = os.path.join(
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")),
    "ui",
    "main_window.py",
)

with open(UI_PATH, "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()

# 说明文案必须覆盖的三个论点（任缺一，误解就还在）
KEY_CLAIMS = [
    ("读数一致", ("读数是一致的", "读数一致")),
    ("算法不同", ("算法",)),
    ("分数不同属正常", ("不完全一致是正常的",)),
    ("判废看硬指标", ("重映射扇区",)),
    ("不代表谁更准", ("不代表谁更准",)),
]

# 「?」弹窗方法名
HELP_METHOD = "_show_help_center"


def _help_body() -> str:
    """取出使用说明弹窗的方法体全文。"""
    start = UI_SRC.index(f"def {HELP_METHOD}")
    end = UI_SRC.index("def _build_ui", start)
    return UI_SRC[start:end]


# ---------------- UI 层：入口存在且不矛盾 ----------------

def test_help_entry_is_the_question_mark_button():
    """口径说明入口是右下角「?」按钮，不该再有独立的「评分说明」按钮。"""
    assert f"def {HELP_METHOD}" in UI_SRC, f"缺少 {HELP_METHOD} 方法"
    assert f"clicked.connect(self.{HELP_METHOD})" in UI_SRC, "「?」按钮未连接到使用说明弹窗"
    assert 'QPushButton("?")' in UI_SRC, "缺少右下角「?」按钮"
    assert 'QPushButton("评分说明")' not in UI_SRC, "仍存在独立的「评分说明」按钮，应并入「?」弹窗"


def test_help_method_exists_and_is_callable():
    """方法必须真实存在且仅收self（供clicked 直连），否则点「?」直接崩。"""
    from ui.main_window import MainWindow

    fn = getattr(MainWindow, HELP_METHOD, None)
    assert callable(fn), f"{HELP_METHOD} 不可调用"
    params = list(inspect.signature(fn).parameters)
    assert params == ["self"], f"签名应只有 self，实际 {params}"


def test_no_stale_v12_teaser_method():
    """旧的预热方法应已移除；若还在，「v1.2 开发中」的自相矛盾措辞可能复活。"""
    assert "def _show_v12_teaser" not in UI_SRC, "_show_v12_teaser 应已被使用说明弹窗取代"
    assert "def _show_score_explain" not in UI_SRC, "_show_score_explain 应已被合并"


def test_no_contradictory_wording():
    """核心回归：软件本体已是 v1.2，界面不得再写「v1.2 开发中」。"""
    for banned in ("v1.2 开发中", "下一个版本正在开发中", "新版预告"):
        assert banned not in UI_SRC, f"界面仍含自相矛盾措辞：{banned}"


def test_help_states_current_version_updates():
    """弹窗要如实说明本版已经更新了什么（盘面扫描、找不到硬盘修复等）。"""
    body = _help_body()
    assert "已经更新了什么" in body, "缺少「本版更新内容」段落"
    for item in ("盘面扫描", "找不到硬盘"):
        assert item in body, f"更新清单缺少：{item}"


def test_help_lists_next_version_plan():
    """弹窗要预告 v1.3 计划——含坛友最想要的邮件/微信提醒。"""
    body = _help_body()
    assert "下一版" in body or "v1.3" in body, "缺少「下一版计划」段落"
    for item in ("提醒", "USB"):
        assert item in body, f"下一版计划缺少：{item}"


def test_help_shows_current_version_number():
    """标题与正文的版本号必须取自 APP_VERSION，不能硬编码——避免下次升版又忘了改。"""
    body = _help_body()
    assert "APP_VERSION" in body, "版本号未取自 APP_VERSION（升版时会漏改）"
    assert not re.search(r"v1\.\d+\.\d+ 已经更新", body), "版本号被硬编码，应改用 APP_VERSION"


def test_help_covers_key_claims():
    """弹窗文案必须把健康分口径的论点说全，缺一条就还有误解空间。"""
    body = _help_body()
    for name, alternatives in KEY_CLAIMS:
        assert any(alt in body for alt in alternatives), f"弹窗文案缺少论点：{name}"


def test_help_uses_rich_text_and_no_result_leak():
    """两点硬要求：①富文本渲染（否则 <br> 会以字面量显示）；
    ②「查看详细报告 / 打开数据文件夹」两个链接已按用户要求（2026-10-07）删除，
    不得残留——若日后要加回来，必须用 self._results 缓存字段（写错会 AttributeError，
    这是本用例最初守护的原始价值）。"""
    body = _help_body()
    assert "setTextFormat(Qt.TextFormat.RichText)" in body, "未启用富文本，<br> 会原样显示"
    assert "查看详细报告" not in body, "「查看详细报告」链接应已按用户要求删除"
    assert "打开数据文件夹" not in body, "「打开数据文件夹」链接应已按用户要求删除"
    assert "去 GitHub 提建议" in body, "唯一保留的反馈链接缺失"


def test_help_offers_feedback_channel():
    """要给出提建议的入口（GitHub），否则反馈渠道仍然断着。"""
    body = _help_body()
    assert "提建议" in body or "Issue" in body, "缺少反馈引导"
    # 用户 2026-10-05 明确：反馈入口要跳 Issues 页，不是仓库首页
    # （「去 GitHub 提建议」却跳首页，等于没接住反馈）
    assert "GITHUB_ISSUES_URL" in body, "反馈入口未跳转到 GitHub Issues 页"


# ---------------- 按钮顺序：盘面扫描在导出报告之前 ----------------

def test_virscan_button_before_export_button():
    """用户要求：盘面扫描按钮排在「导出报告」前面（两者都是检测后的下一步动作）。"""
    vir = UI_SRC.index('self._virscan_btn = QPushButton("盘面扫描")')
    exp = UI_SRC.index('self._btn_export = QPushButton("导出报告")')
    assert vir < exp, "「盘面扫描」应定义在「导出报告」之前"
    # 布局里的添加顺序（= 界面上从左到右的顺序）也要一致
    add_vir = UI_SRC.index("btn_row.addWidget(self._virscan_btn)")
    add_exp = UI_SRC.index("btn_row.addWidget(self._btn_export)")
    assert add_vir < add_exp, "「盘面扫描」应排在「导出报告」之前"
    # 两者必须紧邻，中间不能插别的控件
    between = UI_SRC[add_vir + len("btn_row.addWidget(self._virscan_btn)"): add_exp]
    assert "addWidget" not in between, (
        f"「盘面扫描」与「导出报告」之间不应插入其他控件，实际插了：{between.strip()[:80]!r}"
    )


def test_virscan_button_next_to_detect_button():
    """盘面扫描应紧跟在「开始全盘检测」之后，检测类操作聚在一起。"""
    detect = UI_SRC.index("btn_row.addWidget(self._btn_detect)")
    vir = UI_SRC.index("btn_row.addWidget(self._virscan_btn)")
    exp = UI_SRC.index("btn_row.addWidget(self._btn_export)")
    assert detect < vir < exp, "顺序应为：开始全盘检测 → 盘面扫描 → 导出报告"


# ---------------- 报告层：HTML 报告内说明卡片 ----------------

def _sample_results() -> list[dict]:
    return [
        {
            "model": "金士顿 SV300S37A240G",
            "device_id": "0",
            "bus_type": "SATA",
            "media_type": "SSD",
            "is_ssd": True,
            "size": 240037196800,
            "health_score": 92,
            "grade": "良好",
            "smart_status": "OK",
            "power_on_hours": 8000,
            "temperature": 38,
            "metrics": [],
            "reasons": ["各项指标正常"],
            "suggestions": [],
        }
    ]


def test_report_contains_score_explain_card():
    """导出的 HTML 报告必须带「关于健康分」说明卡片，且在页脚之前。"""
    html = report.build_report_html(_sample_results(), version="1.2.0")
    assert "关于健康分" in html, "报告缺少健康分说明卡片"
    assert html.index("关于健康分") < html.index("本报告由"), "说明卡片应排在页脚之前"


def test_report_explain_text_covers_key_claims():
    """报告文案与 UI 弹窗口径必须一致（同一套说法，不能一个说读数一致另一个没说）。"""
    html = report.build_report_html(_sample_results(), version="1.2.0")
    start = html.index("关于健康分")
    block = html[start : start + 2000]
    for name, alternatives in KEY_CLAIMS:
        assert any(alt in block for alt in alternatives), f"报告说明缺少论点：{name}"


def test_report_explain_not_broken_by_empty_results():
    """空结果（还没检测就点导出）时说明逻辑不能抛异常。"""
    html = report.build_report_html([], version="1.2.0")
    assert "关于健康分" in html, "空结果报告也应保留说明卡片"


def test_ui_and_report_share_same_wording():
    """UI 弹窗与报告卡片用同一套关键词，避免用户在两处看到矛盾说法。"""
    html = report.build_report_html(_sample_results(), version="1.2.0")
    report_block = html[html.index("关于健康分") : html.index("关于健康分") + 2000]
    ui_block = _help_body()
    for keyword in ("重映射扇区", "Unhealthy"):
        assert keyword in report_block, f"报告说明缺少判废关键词：{keyword}"
        assert keyword in ui_block, f"UI 弹窗缺少判废关键词：{keyword}"


def test_no_forum_name_anywhere_in_explain():
    """对外文案不得出现单一论坛名（多论坛策略，见docs/ 升级公告通用版）。"""
    assert not re.search(r"52\s*pojie|吾爱破解", _help_body(), re.IGNORECASE), "弹窗不应出现论坛名"
    html = report.build_report_html(_sample_results(), version="1.2.0")
    assert not re.search(r"52\s*pojie|吾爱破解", html, re.IGNORECASE), "报告不应出现论坛名"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))