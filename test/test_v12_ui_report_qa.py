# -*- coding: utf-8 -*-
"""v1.2 QA 独立测试：offscreen 完整检测 + NVMe 盘详情 + 报告导出抽查。

覆盖：
- DetectWorker 真机完整 7 步检测，每块 NVMe 盘结果带 nvme_health；
- 盘详情含「NVMe 健康数据」块，专业指标网格 6 个 v1.2 新项有值；
- 报告导出到临时目录：NVMe 表完整、提权环境无「需要管理员权限」字样；
  测完删除。
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(TEST_DIR, "..", "src")))
sys.path.insert(0, TEST_DIR)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from ui.main_window import DetectWorker, DiskCard  # noqa: E402

_METRIC_NEW_ITEMS = (
    "累计写入量", "累计读取量", "可用备用空间",
    "使用率（NVMe）", "不安全断电次数", "媒体错误数",
)


def _run_detect() -> list[dict]:
    worker = DetectWorker(None)
    results_box: list[list] = []
    failed_box: list[str] = []
    loop = QEventLoop()
    worker.detect_finished.connect(lambda r: (results_box.append(list(r)), loop.quit()))
    worker.detect_failed.connect(lambda m: (failed_box.append(m), loop.quit()))
    worker.start()
    QTimer.singleShot(180000, loop.quit)
    loop.exec()
    worker.wait(10000)
    assert not failed_box, f"detect_failed: {failed_box}"
    assert results_box, "未收到 detect_finished"
    return results_box[0]


def _grid_texts(card: DiskCard, result: dict) -> dict[str, str]:
    """从专业指标网格取 {label: value} 映射（按 objectName 配对）。"""
    # 直接重建网格（与卡片内部同一实现），避免依赖懒加载细节
    frame = card._build_metrics_grid(result)
    from PySide6.QtWidgets import QGridLayout

    layout = frame.layout()
    assert isinstance(layout, QGridLayout)
    cells: dict[tuple[int, int], str] = {}
    for i in range(layout.count()):
        widget = layout.itemAt(i).widget()
        if isinstance(widget, QLabel):
            row, col, _, _ = layout.getItemPosition(i)
            cells[(row, col)] = widget.text()
    mapping: dict[str, str] = {}
    for (row, col), text in cells.items():
        if (row, col + 1) in cells:
            mapping[text] = cells[(row, col + 1)]
    return mapping


def test_qa_detect_nvme_results_complete():
    results = _run_detect()
    assert len(results) >= 1, "至少应检测到 1 块盘"
    for result in results:
        assert "disk" in result and "verdict" in result
        nvme = result.get("nvme_health")
        assert nvme is not None, f"盘 {result['disk'].get('model')} 缺 nvme_health"
        assert nvme.get("power_on_hours"), f"nvme_health.power_on_hours 为空: {nvme}"
        assert result["verdict"]["level"] in ("healthy", "warning", "danger")


def test_qa_disk_card_nvme_detail_and_metrics():
    results = _run_detect()
    for result in results:
        card = DiskCard(result, admin=True)
        mapping = _grid_texts(card, result)
        for label in _METRIC_NEW_ITEMS:
            assert label in mapping, f"专业指标缺少 v1.2 新项「{label}」"
            value = mapping[label]
            assert value and value != "—", f"「{label}」无值（显示 {value}）"
        # 盘详情含 NVMe 健康数据块
        detail = card._build_detail(result)
        texts = [w.text() for w in detail.findChildren(QLabel)]
        assert "NVMe 健康数据" in texts, f"详情缺少「NVMe 健康数据」块: {texts}"
        joined = "\n".join(texts)
        assert "危险警告" in joined and "可用备用空间" in joined, joined
        # 明细文本（静态方法）
        detail_text = DiskCard._nvme_detail_text(result["nvme_health"])
        assert "通电时间" in detail_text and "累计写入量" in detail_text


def test_qa_export_report_nvme_table_and_wording():
    results = _run_detect()
    from core import report

    tmpdir = tempfile.mkdtemp(prefix="diskguard_qa_")
    path = os.path.join(tmpdir, "report.html")
    try:
        ok, error = report.export_report(path, results)
        assert ok, f"导出失败: {error}"
        assert os.path.isfile(path) and os.path.getsize(path) > 0
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        assert "NVMe 健康数据（直读健康日志）" in html, "报告缺 NVMe 健康数据表"
        for needle in ("危险警告", "可用备用空间", "使用率（NVMe Percentage Used）",
                       "累计写入量", "通电时间", "不安全断电", "媒体错误"):
            assert needle in html, f"报告 NVMe 表缺少「{needle}」"
        # 提权环境：全篇不得出现「需要管理员权限」
        assert "需要管理员权限" not in html, "提权环境下报告不应出现「需要管理员权限」"
        # 卷损坏位应显示「未置位」而非「无法读取」
        assert "未置位" in html, "报告应包含卷损坏位未置位说明"
        assert "v1.2" in html, "报告应带 v1.2 版本号"
    finally:
        if os.path.isfile(path):
            os.remove(path)
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
