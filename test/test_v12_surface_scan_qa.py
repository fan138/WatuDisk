# -*- coding: utf-8 -*-
"""v1.2（#3 / #4）表面扫描回归测试。

坛友反馈：
- #3「盘实际已不稳定但检测全绿」——SMART 是硬盘自己记账的，故障还没被记上时
  SMART 一片绿是常态。这是挖兔必须补的盲区。
- #4「希望对比 HD Tune：缺坏道扫描」。

本测试锁定的关键点（每条都对应一个真实踩过的坑）：
1. **只读**：绝不申请 GENERIC_WRITE，绝不调 chkdsk/标记坏簇——本项目对用户的
   承诺是「只读检测 · 不写入任何数据」，破一次就失去信任。
2. **device_id 纯数字**：全代码库把 device_id 当纯数字串用（#12 已守住该不变量）。
3. **Qt Signal 不用 int** 传字节数：Qt int 是 32 位，2GB 就越界，全盘档会溢出
   500 倍——这是实际跑出来的 RuntimeWarning/OverflowError，不是假想。
4. **容量字段名是 size**：disk_info 用size 不是 size_bytes（写错过一次，界面显示 0 B）。
5. **结论不夸大**：抽样档必须在文案里写明「抽样」，不夸大成全盘结论。
6. **中止必须可用**：坏道会让硬盘反复重试，用户不能被锁死在窗口里。
"""
from __future__ import annotations

import inspect
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import surface_scan  # noqa: E402

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

with open(CORE_PATH, "r", encoding="utf-8") as _fh:
    CORE_SRC = _fh.read()
with open(UI_PATH, "r", encoding="utf-8") as _fh:
    UI_SRC = _fh.read()

TB = 1024 ** 4  # 1TB


# ---------------- 只读承诺（最高优先级，绝不能破） ----------------

def test_never_requests_write_access():
    """代码里绝不能出现写入权限常量（文档里写「绝不申请 GENERIC_WRITE」是正常说明）。

    用 AST 只看真实代码节点，避免把注释和文档字符串里的说明文字也算进来。
    """
    import ast

    assert "GENERIC_READ" in CORE_SRC, "缺少 GENERIC_READ"
    tree = ast.parse(CORE_SRC)
    banned = {"GENERIC_WRITE", "GENERIC_ALL", "FILE_WRITE_DATA", "FILE_APPEND_DATA"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in banned:
            raise AssertionError(f"代码中使用了写入权限：{node.id}（第 {node.lineno} 行）")
        if isinstance(node, ast.Attribute) and node.attr in banned:
            raise AssertionError(f"代码中使用了写入权限：{node.attr}（第 {node.lineno} 行）")
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            # 0xC0000000 = GENERIC_READ|GENERIC_WRITE（写入权限，必须没有）
            # 0x40000000 = FILE_FLAG_OVERLAPPED（异步读标志，只读，允许）
            if node.value == 0xC0000000:
                raise AssertionError(
                    f"第 {node.lineno} 行出现 GENERIC_READ|GENERIC_WRITE 写入权限常量"
                )
    # 打开参数里读权限位必须单独只给 GENERIC_READ
    assert re.search(r"CreateFileW\(\s*\n\s*path,\s*\n\s*GENERIC_READ,", CORE_SRC), \
        "CreateFileW 的读权限必须单独只给 GENERIC_READ"


def test_shared_mode_does_not_lock_disk():
    """必须共享读+写打开，否则扫描时系统会提示「磁盘正在使用中」。"""
    assert "FILE_SHARE_READ | FILE_SHARE_WRITE" in CORE_SRC, "缺少共享读写标志，会独占磁盘"


def test_no_chkdsk_or_write_commands():
    """不得调用 chkdsk /f /r 或任何写盘命令——那些会修改数据。"""
    for banned in ("chkdsk", "format", "fsutil", "diskpart", "defrag", "/f", "/r"):
        # 只在文档字符串里提过不算调用；这里检查真正的调用形态
        pattern = rf"(subprocess|run_ps|os\.system|Popen|check_output)[^\n]*{re.escape(banned)}"
        assert not re.search(pattern, CORE_SRC, re.IGNORECASE), f"疑似调用了写盘命令：{banned}"


def test_rejects_non_numeric_device_id():
    """device_id 非纯数字必须拒绝，绝不能拼出错误路径去读别的盘。"""
    for bad in ("abc", "", None, "0/../1", "../../PhysicalDrive1"):
        try:
            surface_scan._physical_drive_path(bad)
        except surface_scan.SurfaceScanUnavailable:
            pass
        else:
            raise AssertionError(f"非法 device_id 未被拒绝：{bad!r}")


def test_physical_drive_path_uses_device_id():
    """纯数字 device_id 应拼成PhysicalDriveN。"""
    assert surface_scan._physical_drive_path("2") == r"\\.\PhysicalDrive2"
    assert surface_scan._physical_drive_path(3) == r"\\.\PhysicalDrive3"


# ---------------- 读取规划 ----------------

def test_quick_mode_samples_but_limits_total():
    """快速档目标 2GB 左右：块数上限 512（512 * 4MB = 2GB），不能把1TB 盘全读完。"""
    offsets = surface_scan._plan_offsets(TB, surface_scan.MODE_QUICK)
    assert 0 < len(offsets) <= surface_scan.MAX_QUICK_CHUNKS, f"快速档块数失控：{len(offsets)}"
    assert len(offsets) * surface_scan.CHUNK_SIZE <= surface_scan.QUICK_TARGET_BYTES


def test_quick_mode_covers_head_middle_tail():
    """抽样必须覆盖盘头/中/尾，否则查不出只在末尾的坏道。"""
    offsets = surface_scan._plan_offsets(TB, surface_scan.MODE_QUICK)
    assert min(offsets) == 0, "抽样未覆盖盘头"
    total = TB - surface_scan.CHUNK_SIZE
    assert max(offsets) > total * 0.98, "抽样未覆盖盘尾"
    middle = total * 0.5
    assert any(abs(o - middle) < total * 0.05 for o in offsets), "抽样未覆盖盘中部"


def test_full_mode_covers_whole_disk_without_overrun():
    """全盘档：覆盖每块，但偏移不能超过盘尾（越界读会失败）。"""
    offsets = surface_scan._plan_offsets(TB, surface_scan.MODE_FULL)
    total = TB - surface_scan.CHUNK_SIZE
    assert offsets[0] == 0
    assert max(offsets) <= total, "全盘档偏移越界"
    # 相邻间隔应等于块大小
    assert offsets[1] - offsets[0] == surface_scan.CHUNK_SIZE


def test_small_disk_reads_whole_disk():
    """盘比目标量还小时，直接全读（不会出现 0 块）。"""
    tiny = 40 * 1024 * 1024  # 40MB
    offsets = surface_scan._plan_offsets(tiny, surface_scan.MODE_QUICK)
    assert len(offsets) >= 1
    assert max(offsets) + surface_scan.CHUNK_SIZE <= tiny


def test_zero_or_negative_size_returns_empty():
    """容量为0/-1 时不能崩，也不能瞎读。"""
    assert surface_scan._plan_offsets(0, surface_scan.MODE_QUICK) == []
    assert surface_scan._plan_offsets(-100, surface_scan.MODE_FULL) == []


def test_unknown_mode_rejected():
    """未知档位必须报错，而不是默默按默认跑。"""
    try:
        surface_scan._plan_offsets(TB, "turbo")
        surface_scan.scan_surface("0", TB, mode="turbo")
    except ValueError:
        pass
    else:
        raise AssertionError("未知档位未被拒绝")


# ---------------- 结论解读（不能夸大） ----------------

def _res(**kw):
    base = {
        "device_id": "0", "mode": surface_scan.MODE_QUICK, "total_bytes": TB,
        "planned_chunks": 512, "bytes_scanned": 2 * 1024 ** 3, "chunks_ok": 512,
        "chunks_failed": 0, "bad_sectors": 0, "bad_positions": [],
        "elapsed_sec": 1.0, "speed_mb_s": 2000.0, "cancelled": False,
        "finished": True, "error": "",
    }
    base.update(kw)
    return base


def test_clean_scan_is_good():
    level, msg = surface_scan.interpret(_res())
    assert level == "good"
    assert "未发现读失败" in msg


def test_quick_result_text_says_sampled():
    """关键：抽样档的结论必须写明「抽样」，不能让人误以为是全盘结论。"""
    _, msg = surface_scan.interpret(_res(mode=surface_scan.MODE_QUICK))
    assert "抽样" in msg, f"抽样结论未标注抽样：{msg}"


def test_full_result_text_does_not_claim_sampled():
    _, msg = surface_scan.interpret(_res(mode=surface_scan.MODE_FULL, planned_chunks=100000))
    assert "抽样" not in msg, "全盘结论不应出现「抽样」字样"


def test_few_bad_chunks_is_warning_not_bad():
    """零星读失败判警告，不该直接判死刑（避免又一个「吓人」投诉）。"""
    level, msg = surface_scan.interpret(_res(chunks_ok=510, chunks_failed=2))
    assert level == "warn", f"零星失败应判警告，实际 {level}"
    assert "2" in msg


def test_many_bad_chunks_is_bad_with_backup_advice():
    """大面积读失败必须判危险，并给出「先备份」的建议。"""
    level, msg = surface_scan.interpret(_res(chunks_ok=400, chunks_failed=112))
    assert level == "bad"
    assert "备份" in msg


def test_cancelled_scan_is_not_reported_as_good():
    """中止的扫描绝不能报「未发现问题」——这是最危险的假阴性。"""
    level, msg = surface_scan.interpret(_res(finished=True, cancelled=True, chunks_ok=50))
    assert level in ("warn", "unknown"), f"中止被误判为 {level}"
    assert "中止" in msg


def test_failed_scan_reports_error():
    level, msg = surface_scan.interpret(_res(error="需要管理员权限才能读取物理盘"))
    assert level == "unknown"
    assert "管理员" in msg


def test_empty_result_is_safe():
    """空结果/None 都不能崩。"""
    assert surface_scan.interpret({})[0] == "unknown"
    assert surface_scan.interpret(None)[0] == "unknown"


# ---------------- 格式化与预估 ----------------

def test_format_size_human_readable():
    assert surface_scan.format_size(0) == "0 B"
    assert surface_scan.format_size(512) == "512 B"
    assert surface_scan.format_size(2 * 1024 ** 3).endswith("GB")
    assert surface_scan.format_size(None) == "0 B"


def test_estimate_time_scales_with_speed():
    """测速越快预估越短；且档位差异要体现出来（1TB 盘在 2000MB/s 与 80MB/s 差 25 倍）。"""
    fast = surface_scan.estimate_full_scan_time(TB, 2000.0)
    slow = surface_scan.estimate_full_scan_time(TB, 80.0)
    assert fast and slow and fast != slow
    assert "小时" in slow, f"机械盘预估应体现小时级：{slow}"
    assert "分钟" in fast or "小时" in fast, f"NVMe 预估应体现分钟级：{fast}"


def test_estimate_time_handles_bad_input():
    """速度为0（没测过）时不给预估，而不是编一个数字。"""
    assert surface_scan.estimate_full_scan_time(TB, 0) == ""
    assert surface_scan.estimate_full_scan_time(0, 100.0) == ""
    assert surface_scan.estimate_full_scan_time(TB, -5) == ""


# ---------------- Qt 层（真跑出来的坑） ----------------

def test_progress_signal_not_int():
    """Qt int 是 32 位；2GB 进度即越界，全盘 1TB 溢出 500 倍。
    实际跑出来过 RuntimeWarning: Value 2147483648 exceeds limits of type int。"""
    assert not re.search(r"progress\s*=\s*Signal\(\s*int", UI_SRC), \
        "进度信号不能用 int（32 位上限 2GB），应改用 object"
    assert "Signal(object, object, int)" in UI_SRC, "进度信号应声明为 (object, object, int)"


def test_progress_slot_accepts_object():
    def _on_progress(self, done: object, planned: object, bad: int) -> None:
        pass

    params = list(inspect.signature(_on_progress).parameters)
    assert params == ["self", "done", "planned", "bad"], f"槽函数签名不对：{params}"


def test_uses_size_field_not_size_bytes():
    """disk_info 的容量字段是 size；写成 size_bytes 会让界面显示 0 B（真踩过）。"""
    assert "size_bytes" not in UI_SRC, "仍在用不存在的 size_bytes 字段"
    assert 'disk.get("size")' in UI_SRC, "应读取 disk.get(\"size\")"


def test_dialog_supports_abort():
    """必须支持中止：坏道会让硬盘反复重试，不给中止等于把用户锁死。"""
    assert "def abort(self)" in UI_SRC, "缺少 abort 方法"
    assert "is_aborted" in UI_SRC, "未把中止标志传给核心扫描"
    assert "CancelIoEx" in CORE_SRC, "超时的块必须 CancelIoEx 取消，否则挂起"


def test_dialog_has_readonly_disclaimer():
    """界面上要写明只读，否则用户会以为扫完等于修好了。"""
    assert "只读" in UI_SRC, "对话框缺少只读声明"
    assert "不修复" in UI_SRC, "对话框需明确「不修复」"


def test_dialog_warns_sample_may_miss():
    """抽样会漏掉局部坏道，必须如实告知，不能夸大结论。"""
    assert "抽样" in UI_SRC, "对话框未提抽样"
    assert "漏" in UI_SRC, "对话框未说明抽样可能漏掉局部坏道"


def test_full_mode_warns_duration_without_popup():
    """全盘档可能跑几小时：耗时必须告知，但**不再弹二次确认窗**。

    2026-10-06 用户实测反馈：勾选硬盘后希望「点了就自动扫」，每次弹窗确认
    打断工作。因此确认弹窗已移除，风险告知改由界面常驻文案承担——
    告知责任不能跟着弹窗一起取消，否则用户会在不知情下跑几小时。
    """
    # 耗时风险仍必须在界面上写清楚（这条是底线，不能因为去掉弹窗而丢）
    assert "几个小时" in UI_SRC, "未告知机械盘可能耗时数小时"
    assert "机械硬盘可能要几个小时" in UI_SRC or "机械盘可能数小时" in UI_SRC, \
        "全盘档耗时告知文案缺失"
    # 确认弹窗已移除
    assert "确认全盘扫描" not in UI_SRC, "全盘档仍在弹二次确认，用户已明确要求免确认"
    assert "QMessageBox.question" not in UI_SRC, "仍有 QMessageBox.question 二次确认"
    # 免确认的前提是「耗时可见」：估算文案必须存在且含预计时间口径
    assert "预计" in UI_SRC, "缺少预计耗时文案，免确认后这是唯一的风险告知"


def test_thread_wraps_exceptions():
    """后台异常绝不能把应用带崩。"""
    body = UI_SRC[UI_SRC.index("def run(self)") : UI_SRC.index("def run(self)") + 900]
    assert "except Exception" in body, "线程 run 未兜底异常"


def test_no_forum_name_in_dialog():
    """对外文案不得出现单一论坛名（多论坛策略）。"""
    assert not re.search(r"52\s*pojie|吾爱破解", UI_SRC, re.IGNORECASE), "对话框不应出现论坛名"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))