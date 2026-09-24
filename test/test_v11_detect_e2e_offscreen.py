# -*- coding: utf-8 -*-
"""v1.1 七步体检端到端测试（QA 自编，offscreen 完整跑 DetectWorker）。

覆盖：
- 真机完整跑 7 步：step_started / step_result 依序到达、每步 summary 非空、
  结果盘卡片数 == 物理盘数；
- 失败容错：mock powershell_runner.run_ps_json 返回 None（模拟权限不足 /
  PowerShell 整体失败），验证步骤逐个落「橙色 !」但流程继续不崩溃，
  后续步骤照常发信号，最终仍 emit detect_finished。

运行需 QT_QPA_PLATFORM=offscreen（文件内自设）。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(TEST_DIR, "..", "src")))
sys.path.insert(0, TEST_DIR)

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from ui.main_window import DetectWorker  # noqa: E402


class SignalRecorder:
    """收集 DetectWorker 的全部信号（跨线程排队连接下安全）。"""

    def __init__(self, worker: DetectWorker) -> None:
        self.started: list[int] = []
        self.results: list[tuple[int, bool, str]] = []
        self.finished: list[list] = []
        self.failed: list[str] = []
        worker.step_started.connect(self.started.append)
        worker.step_result.connect(lambda i, ok, s: self.results.append((i, ok, s)))
        worker.detect_finished.connect(lambda r: self.finished.append(list(r)))
        worker.detect_failed.connect(self.failed.append)


def _run_worker(worker: DetectWorker, timeout_ms: int = 120000) -> SignalRecorder:
    recorder = SignalRecorder(worker)
    loop = QEventLoop()
    worker.detect_finished.connect(lambda _r: loop.quit())
    worker.detect_failed.connect(lambda _m: loop.quit())
    worker.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    worker.wait(5000)
    return recorder


def test_detect_worker_seven_steps_in_order_real_machine():
    worker = DetectWorker(None)
    recorder = _run_worker(worker)

    assert not recorder.failed, f"detect_failed 被触发：{recorder.failed}"
    assert recorder.finished, "未收到 detect_finished"
    results = recorder.finished[0]

    # 7 个 step_started 依序到达
    assert recorder.started == list(range(7)), f"step_started 顺序异常：{recorder.started}"
    # 7 个 step_result 依序到达，且每步 summary 非空
    assert [r[0] for r in recorder.results] == list(range(7)), (
        f"step_result 顺序异常：{[r[0] for r in recorder.results]}"
    )
    for index, ok, summary in recorder.results:
        assert isinstance(summary, str) and summary.strip(), f"步骤 {index} summary 为空"
    # 结果盘卡片数 == 物理盘数
    from core.disk_info import get_physical_disks

    disks = get_physical_disks()
    assert len(results) == len(disks), f"结果 {len(results)} 块 vs 物理盘 {len(disks)} 块"
    # 每个结果都带完整结构
    for result in results:
        assert "disk" in result and "verdict" in result
        verdict = result["verdict"]
        assert isinstance(verdict.get("score"), int)
        assert verdict["level"] in ("healthy", "warning", "danger")
        assert verdict["reasons"], "建议（reasons）不应为空"


def test_detect_worker_failure_tolerance_all_ps_fails():
    """mock run_ps_json 永远返回 None：0/1/3/5 步落橙!，但 7 步流程完整走完不崩溃。"""
    import core.powershell_runner as ps_runner
    import ui.main_window as mw

    original = ps_runner.run_ps_json
    # DetectWorker 内部 from core import disk_info -> disk_info.run_ps_json 是同一函数对象，
    # 两个命名空间都要替换
    try:
        ps_runner.run_ps_json = lambda *a, **k: None
        mw_run = None
        # main_window._detect 内通过 disk_info.get_physical_disks() 调用，
        # 而 disk_info 模块内引用的 run_ps_json 来自 core.powershell_runner 的绑定，
        # 模块级 from-import 已把函数对象绑定进 core.disk_info 命名空间
        import core.disk_info as disk_info_mod

        original_disk_info = disk_info_mod.run_ps_json
        disk_info_mod.run_ps_json = lambda *a, **k: None
        del mw_run

        worker = DetectWorker(None)
        recorder = _run_worker(worker)

        assert recorder.finished, "全部 PowerShell 失败时仍应正常完成（0 块盘结果）"
        assert recorder.finished[0] == [], "枚举失败时结果应为空列表"
        assert not recorder.failed, f"不应触发 detect_failed：{recorder.failed}"
        assert [r[0] for r in recorder.results] == list(range(7)), "失败时 7 步信号仍应依序发完"

        ok_flags = {index: ok for index, ok, _s in recorder.results}
        # 步骤 0/1（枚举、健康状态）与 3（可靠性计数器）、5（卷损坏）应失败（橙!）
        assert ok_flags[0] is False, "步骤 0 应落橙!"
        assert ok_flags[1] is False, "步骤 1 应落橙!"
        assert ok_flags[3] is False, "步骤 3 应落橙!"
        assert ok_flags[5] is False, "步骤 5 应落橙!"
        # 步骤 2（无 SATA 盘可解析）、4（0 条事件）、6（0 块盘评分）应成功
        assert ok_flags[2] is True, "步骤 2 无 SATA 盘时应判成功继续"
        assert ok_flags[4] is True, "步骤 4 空事件列表应判成功继续"
        assert ok_flags[6] is True, "步骤 6 生成空结果应判成功继续"
        # 失败步骤的 summary 非空（供界面展示原因）
        for index, ok, summary in recorder.results:
            if not ok:
                assert summary.strip(), f"失败步骤 {index} 的 summary 为空"
    finally:
        ps_runner.run_ps_json = original
        import core.disk_info as disk_info_mod

        disk_info_mod.run_ps_json = original_disk_info


def test_detect_worker_steps_definition():
    """步骤清单固定为 7 步且命名完整。"""
    assert len(DetectWorker.STEPS) == 7
    assert DetectWorker.STEPS[0] == "枚举硬盘设备"
    assert DetectWorker.STEPS[-1] == "生成评分与建议"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
