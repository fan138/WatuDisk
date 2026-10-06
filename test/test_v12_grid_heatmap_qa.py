# -*- coding: utf-8 -*-
"""v1.2 盘面地图（20×20 格子热力图）回归测试。

起因（用户原话）：「这个界面太单调了……我记得有一个小软件，界面是 100 个还是
多少个方格子，每扫描一个格子由灰色变成绿色，检测到坏块就橙色、红色……
（本软件是六色提醒），更能发挥出软件小而强悍的优势。」

本测试锁定的关键点（每条都对应一个真实的设计取舍）：
1. **两档共用同一套 400 格划分**：快速档每格抽 1 块，全盘档每格逐块读完，
   两张图才能直接对比；否则「快速档一片绿、全盘档一片红」无法解释。
2. **颜色不只看读没读出来，还看读得多慢**：坏道在彻底读不出来之前往往先
   表现为明显变慢，这是专业坏块工具的核心维度，值得补。
3. **阈值用相对值**（本次扫描成功块耗时中位数为基准）：机械盘几十毫秒、
   NVMe 几毫秒，用绝对毫秒会把两种盘的语义搞反。
4. **拿不到基准时只判读没读出来，绝不乱标黄橙**——宁可漏标不可误标，
   这是本项目「不吓人」的一贯口径。
5. **防误导**：快速档把 400 格刷满很容易被理解成「整盘都扫过」，
   所以界面必须写清抽查密度。这是这条需求最大的陷阱。
6. 全盘档几十万块，基准只能等距采样，否则内存与算力都失控。
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import surface_scan as ss  # noqa: E402

CORE_PATH = os.path.join(
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")),
    "core",
    "surface_scan.py",
)
UI_PATH = os.path.join(
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")),
    "ui",
    "surface_scan_dialog.py",
)
REPORT_PATH = os.path.join(
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")),
    "core",
    "report.py",
)
THEME_PATH = os.path.join(
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")),
    "ui",
    "theme.py",
)

with open(CORE_PATH, "r", encoding="utf-8") as _fh:
    CORE_SRC = _fh.read()
with open(UI_PATH, "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()
with open(REPORT_PATH, "r", encoding="utf-8") as _fh:
    REPORT_SRC = _fh.read()
with open(THEME_PATH, "r", encoding="utf-8") as _fh:
    THEME_SRC = _fh.read()

TB = 1024 ** 4  # 1TB


# ---------------- 区间划分：两档共用同一套 400 格 ----------------

def test_grid_is_20x20():
    """20×20 = 400 格：够密能定位坏块集中在哪一段，够疏不至于扫太久。"""
    assert ss.GRID_COLS == 20 and ss.GRID_ROWS == 20
    assert ss.GRID_CELLS == 400


def test_quick_mode_samples_exactly_one_block_per_cell():
    """快速档块数必须正好等于格子数：每格抽 1 块，扫完即填满热力图。

    若块数少于 400，图上一片灰但扫描其实已经结束了——观感像「扫了一半」；
    若多于 400，又会出现「一格多块」导致快速档与全盘档语义不一致。
    """
    offsets = ss._plan_offsets(TB, ss.MODE_QUICK)
    assert len(offsets) == ss.GRID_CELLS, f"快速档应抽 400 块，实际 {len(offsets)}"
    # 仍要守住原有的上限与总量约束
    assert len(offsets) <= ss.MAX_QUICK_CHUNKS
    assert len(offsets) * ss.CHUNK_SIZE <= ss.QUICK_TARGET_BYTES


def test_quick_mode_still_covers_head_middle_tail():
    """改成 400 块后仍要覆盖盘头/中/尾，不能因为凑格子数就漏掉盘尾。"""
    offsets = ss._plan_offsets(TB, ss.MODE_QUICK)
    assert min(offsets) == 0, "抽样未覆盖盘头"
    total = TB - ss.CHUNK_SIZE
    assert max(offsets) > total * 0.98, "抽样未覆盖盘尾"
    assert any(abs(o - total * 0.5) < total * 0.05 for o in offsets), "抽样未覆盖盘中部"


def test_cell_mapping_one_to_one_in_quick_mode():
    """快速档：第 i 块就落在第 i 格（一一对应）。"""
    for index in (0, 1, 199, 399):
        assert ss.cell_of_index(index, 400) == index


def test_cell_mapping_proportional_in_full_mode():
    """全盘档：按物理位置比例聚合到同一套区间，两档图才能对比。"""
    total = 262144  # 1TB / 4MB
    assert ss.cell_of_index(0, total) == 0
    assert ss.cell_of_index(total - 1, total) == ss.GRID_CELLS - 1
    mid = ss.cell_of_index(total // 2, total)
    assert 199 <= mid <= 200, f"正中间应落在中间格，实际 {mid}"


def test_cell_mapping_never_out_of_range():
    """极端输入也不能越界，否则界面画格子会崩。"""
    assert ss.cell_of_index(0, 0) == 0
    assert ss.cell_of_index(-5, 400) == 0
    assert ss.cell_of_index(999999, 400) == ss.GRID_CELLS - 1


# ---------------- 六色状态判定 ----------------

def test_cell_state_order_is_severity_ascending():
    """状态常量顺序即严重程度，界面/报告都靠这个顺序画图例。"""
    assert (ss.CELL_PENDING < ss.CELL_OK < ss.CELL_SLOW
            < ss.CELL_VERY_SLOW < ss.CELL_FAILED < ss.CELL_FAILED_RUN)


def test_classify_pending():
    assert ss.classify_cell(0, 0, 0, 0.0, 5.0) == ss.CELL_PENDING


def test_classify_ok():
    assert ss.classify_cell(1, 0, 0, 5.0, 5.0) == ss.CELL_OK
    # 略慢一点点（2.9 倍）仍算正常，不要把正常盘刷成一片黄
    assert ss.classify_cell(1, 0, 0, 14.5, 5.0) == ss.CELL_OK


def test_classify_slow_and_very_slow():
    assert ss.classify_cell(1, 0, 0, 16.0, 5.0) == ss.CELL_SLOW       # 3.2 倍
    assert ss.classify_cell(1, 0, 0, 60.0, 5.0) == ss.CELL_VERY_SLOW  # 12 倍


def test_classify_failure_beats_slow():
    """读失败优先于慢：都读不出来了，颜色必须是最严重的那一档。"""
    assert ss.classify_cell(4, 1, 1, 0.0, 5.0) == ss.CELL_FAILED
    assert ss.classify_cell(4, 3, 3, 0.0, 5.0) == ss.CELL_FAILED_RUN


def test_classify_consecutive_failure_is_darkest():
    """连续读失败 = 成片坏区，必须比单个读失败更醒目。"""
    assert ss.classify_cell(5, 2, 2, 0.0, 5.0) == ss.CELL_FAILED_RUN
    # 失败两块但不连续，仍按单个读失败处理
    assert ss.classify_cell(5, 2, 1, 0.0, 5.0) == ss.CELL_FAILED


def test_classify_without_baseline_never_marks_slow():
    """拿不到基准时绝不乱标黄橙——宁可漏标不可误标（不吓人是一贯口径）。"""
    for avg in (0.0, 5.0, 999.0):
        assert ss.classify_cell(1, 0, 0, avg, 0.0) == ss.CELL_OK, f"无基准却标了慢：{avg}"


def test_threshold_is_relative_not_absolute():
    """同一份绝对耗时，在慢盘上是「正常」、在快盘上是「很慢」——阈值必须相对。

    机械盘天然几十毫秒、NVMe 几毫秒，用绝对毫秒会把两种盘的语义搞反。
    """
    hdd_baseline = 40.0
    nvme_baseline = 2.0
    assert ss.classify_cell(1, 0, 0, 45.0, hdd_baseline) == ss.CELL_OK
    assert ss.classify_cell(1, 0, 0, 45.0, nvme_baseline) == ss.CELL_VERY_SLOW


def test_live_state_during_scan():
    """扫描途中的暂定色：还算不出基准，只能判读没读出来。"""
    assert ss.live_cell_state(False, 0) == ss.CELL_OK
    assert ss.live_cell_state(True, 1) == ss.CELL_FAILED
    assert ss.live_cell_state(True, 2) == ss.CELL_FAILED_RUN


# ---------------- 基准采样（全盘档几十万块） ----------------

def test_timing_sampling_is_bounded():
    """全盘档块数巨大，基准只能等距采样，否则内存与算力都失控。"""
    total = 262144  # 1TB / 4MB
    step = ss.timing_step_for(total)
    sampled = [i for i in range(total) if i % step == 0]
    assert 0 < len(sampled) <= ss._MAX_TIMING_SAMPLES + 1, f"采样量失控：{len(sampled)}"
    assert sampled[-1] >= total - step, "等距采样必须覆盖到盘尾，不能只采盘头"


def test_timing_sampling_small_scan_takes_every_block():
    """块数少时每块都采样，样本越多基准越准。"""
    assert ss.timing_step_for(400) == 1
    assert ss.timing_step_for(0) == 1


def test_finalize_counts_and_codes():
    """扫完要给 400 格定色、统计各色数量，并压成字符串存盘。"""
    result = ss._empty_result("0", ss.MODE_QUICK, TB, 400)
    blocks = [1] * 400
    failed = [0] * 400
    ms = [5.0] * 400
    run = [0] * 400
    ss._finalize_cells(result, blocks, failed, ms, run, [5.0] * 400)
    assert len(result["cells"]) == ss.GRID_CELLS
    assert result["cells_scanned"] == 400
    assert result["bad_cells"] == 0
    assert len(result["cells_code"]) == ss.GRID_CELLS
    assert result["baseline_ms"] == 5.0


def test_finalize_marks_bad_and_slow_cells():
    blocks = [1] * 400
    failed = [0] * 400
    ms = [5.0] * 400
    run = [0] * 400
    failed[7] = 1
    run[7] = 1
    ms[8] = 60.0   # 12 倍基准 → 很慢
    ms[9] = 20.0   # 4 倍基准 → 偏慢
    result = ss._empty_result("0", ss.MODE_QUICK, TB, 400)
    ss._finalize_cells(result, blocks, failed, ms, run, [5.0] * 400)
    assert result["cells"][7] == ss.CELL_FAILED
    assert result["cells"][8] == ss.CELL_VERY_SLOW
    assert result["cells"][9] == ss.CELL_SLOW
    assert result["bad_cells"] == 1
    assert result["slow_cells"] == 2
    assert result["very_slow_cells"] == 1


# ---------------- 编解码（存 JSON / 写报告用） ----------------

def test_encode_decode_roundtrip():
    cells = [ss.CELL_OK] * 398 + [ss.CELL_FAILED, ss.CELL_FAILED_RUN]
    code = ss.encode_cells(cells)
    assert len(code) == ss.GRID_CELLS
    assert ss.decode_cells(code) == cells


def test_decode_bad_input_is_safe():
    """数据被手改坏/版本不兼容时，返回全灰而不是让界面崩。"""
    for bad in (None, "", "abc", 123, "0" * 399, "9" * 400, ["1"]):
        decoded = ss.decode_cells(bad)
        assert len(decoded) == ss.GRID_CELLS
        assert all(state == ss.CELL_PENDING for state in decoded)


def test_encode_bad_input_returns_empty():
    assert ss.encode_cells(None) == ""
    assert ss.encode_cells([1, 2, 3]) == ""
    assert ss.encode_cells(["x"] * 400) == "0" * 400


def test_cell_counts_summary():
    counts = ss.cell_counts([ss.CELL_OK] * 5 + [ss.CELL_SLOW] * 2 + [ss.CELL_FAILED])
    assert counts[ss.CELL_OK] == 5
    assert counts[ss.CELL_SLOW] == 2
    assert counts[ss.CELL_FAILED] == 1
    assert counts[ss.CELL_PENDING] == 0
    assert ss.cell_counts(None)[ss.CELL_OK] == 0


def test_cell_color_matches_six_grade_palette():
    """格子六色必须沿用主界面健康分的六档色，口径统一不用重新记。"""
    assert ss.CELL_COLORS[ss.CELL_OK] == "#67C23A"
    assert ss.CELL_COLORS[ss.CELL_SLOW] == "#D99A0B"
    assert ss.CELL_COLORS[ss.CELL_VERY_SLOW] == "#DD6B1D"
    assert ss.CELL_COLORS[ss.CELL_FAILED] == "#C93A3A"
    assert ss.CELL_FAILED_RUN and ss.CELL_COLORS[ss.CELL_FAILED_RUN] == "#8A1E1E"
    for color in (ss.CELL_COLORS[ss.CELL_OK], ss.CELL_COLORS[ss.CELL_SLOW],
                  ss.CELL_COLORS[ss.CELL_VERY_SLOW], ss.CELL_COLORS[ss.CELL_FAILED],
                  ss.CELL_COLORS[ss.CELL_FAILED_RUN]):
        assert color in THEME_SRC, f"格子色 {color} 未出现在主题里，界面与图例可能不同色"
    assert ss.cell_color(None) == ss.CELL_COLORS[ss.CELL_PENDING]
    assert ss.cell_color(999) == ss.CELL_COLORS[ss.CELL_PENDING]


def test_six_labels_for_legend():
    assert len(ss.CELL_LABELS) == 6
    for state in (ss.CELL_PENDING, ss.CELL_OK, ss.CELL_SLOW,
                  ss.CELL_VERY_SLOW, ss.CELL_FAILED, ss.CELL_FAILED_RUN):
        assert ss.CELL_LABELS.get(state), f"状态 {state} 缺图例文案"


# ---------------- 结论文案要带上「慢」的预警 ----------------

def test_good_result_mentions_slow_cells_as_early_warning():
    """读得慢但还没失败：值得说一句（提前预警），但不改变等级。

    慢也可能是盘内外圈速度差、SMR 叠瓦盘、USB 桥接等正常原因，
    直接判警告又会变成新的「吓人」投诉，所以只补充说明。
    """
    base = ss._empty_result("0", ss.MODE_QUICK, TB, 400)
    base.update({"finished": True, "chunks_ok": 400, "bytes_scanned": 1600 * 1024 ** 2})
    level, msg = ss.interpret(dict(base, slow_cells=4))
    assert level == "good", "慢不应改变等级"
    assert "偏慢" in msg, "未提示存在偏慢区域"
    level2, msg2 = ss.interpret(dict(base, slow_cells=0))
    assert level2 == "good" and "偏慢" not in msg2


# ---------------- 界面：真的有格子图 ----------------

def test_ui_has_surface_grid_widget():
    """界面必须有 20×20 的格子控件，而不是只有一个进度条。"""
    assert "class SurfaceGrid(QWidget)" in UI_SRC, "缺少盘面格子控件"
    assert "def paintEvent(self, event)" in UI_SRC, "格子控件没有绘制逻辑"
    assert "GRID_CELLS" in UI_SRC, "格子数量未与 core 对齐"


def test_grid_paints_400_cells_with_core_colors():
    """颜色一律取自 core，避免界面另写一套导致两处不同色。"""
    body = UI_SRC[UI_SRC.index("def paintEvent"):]
    assert "cell_color" in body, "绘制时未使用 core 的统一配色"


def test_ui_updates_grid_live():
    """扫一块亮一格，而不是等扫完才出图——用户要的是「看着它扫」。"""
    assert "on_cell" in UI_SRC, "未把逐格回调传进核心扫描"
    assert "cell_changed = Signal(int, int)" in UI_SRC, "缺少逐格刷新信号"
    assert "def _on_cell_changed" in UI_SRC, "界面未接逐格刷新"


def test_ui_throttles_cell_signals():
    """全盘档几十万块，若每块都发跨线程信号会冲垮界面事件队列。"""
    body = UI_SRC[UI_SRC.index("def _on_cell(self"):]
    body = body[: body.index("def _on_finished")] if "def _on_finished" in body else body[:600]
    assert "_cell_seen" in body, "未做去重，几十万次信号会冲垮界面"
    assert "return" in body, "颜色没变化时不应重复发信号"


def test_ui_finalizes_with_baseline_colors():
    """扫完要用最终颜色整体重绘——途中的暂定色还算不出「慢」。"""
    body = UI_SRC[UI_SRC.index("def _on_finished"):]
    assert "set_all" in body, "扫完未用最终颜色重绘"
    assert "decode_cells" in body or "cells" in body, "未取最终格子数据"


def test_ui_has_six_color_legend():
    assert "def _build_legend" in UI_SRC, "缺少图例"
    assert "_LEGEND_ORDER" in UI_SRC, "图例顺序未定义"
    for label in ("正常", "偏慢", "很慢", "读失败", "连续读失败", "未扫描"):
        assert label in ss.CELL_LABELS.values() or label in UI_SRC, f"图例缺：{label}"


def test_ui_shows_scanned_cell_counter():
    assert "已扫" in UI_SRC and "400 格" in UI_SRC, "未显示已扫格数，用户不知道进度"


# ---------------- 防误导：抽查密度必须说清楚（本需求最大陷阱） ----------------

def test_ui_declares_sampling_density():
    """快速档把 400 格刷满，很容易被理解成「整盘都扫过」——必须写明抽查密度。

    这是这条需求最大的陷阱：图很好看，但看错含义比没有图更危险。
    """
    assert "抽查密度" in UI_SRC, "未标注抽查密度"
    assert "每个区域抽查 1 块" in UI_SRC, "未说明快速档每格只抽 1 块"
    assert "不等于整格都扫过" in UI_SRC, "未澄清「变绿 ≠ 整格扫过」"


def test_ui_full_mode_density_says_reads_every_block():
    assert "全部逐块读完" in UI_SRC, "全盘档未说明是逐块读完"


def test_core_docstring_warns_sampling_limit():
    """core 的文档里也要写清抽样的局限，防止后来改代码的人忘掉。"""
    head = CORE_SRC[: CORE_SRC.index("def _load_kernel32")]
    assert "抽查" in head or "抽样" in head, "核心模块未写明抽样局限"


# ---------------- 报告里的盘面地图 ----------------

def test_report_renders_grid_map():
    """报告里也要画图：报告是给别人看的，有图比一行字直观得多。"""
    assert "def _grid_map_html" in REPORT_SRC, "报告未渲染盘面地图"
    assert "def _grid_legend_html" in REPORT_SRC, "报告未渲染图例"

    from core import report

    cells = [ss.CELL_OK] * 398 + [ss.CELL_FAILED, ss.CELL_FAILED_RUN]
    html = report._grid_map_html(ss.encode_cells(cells))
    assert html.count("<i style='background:") == ss.GRID_CELLS, "报告格子数不对"
    assert "#C93A3A" in html and "#8A1E1E" in html, "报告未画出读失败的红色"


def test_report_skips_empty_grid():
    """没扫过的盘不放空图，免得占地方还让人以为扫过。"""
    from core import report

    assert report._grid_map_html("") == ""
    assert report._grid_map_html(ss.encode_cells([ss.CELL_PENDING] * 400)) == ""


def test_report_grid_uses_core_colors_not_hardcoded():
    """报告颜色必须取自 core，否则界面改色后报告会脱节。"""
    assert "cell_color" in REPORT_SRC, "报告硬编码了颜色，未与 core 同源"


def test_report_section_renamed_to_disk_surface():
    """按钮改叫「盘面扫描」后，报告标题要跟着改，不能一半一半。"""
    assert "盘面扫描（最近一次）" in REPORT_SRC, "报告标题未同步改名"


def test_report_shows_slow_cell_stats():
    """报告要带上「偏慢区域」的统计，和界面图例对得上。"""
    assert "读取偏慢区域" in REPORT_SRC, "报告未统计偏慢区域"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
