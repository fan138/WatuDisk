# -*- coding: utf-8 -*-
"""v1.2 QA 总回归编排器：v1.2 QA 新增 + v1.0/v1.1 既有用例 + selftest + smoke。

已知假失败（v1.1 遗留，不计入失败）：
- test_v11_autostart_real：QA 沙箱 safe-delete 可能拦截启动文件夹快捷方式
  清理导致模块退出码 1；只要用例全部 PASS 且无残留即视为通过。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

QA_V12_MODULES = [
    "test_v12_nvme_parse_qa",
    "test_v12_verdict_nvme_qa",
    "test_v12_green_audit_qa",
    "test_v12_real_machine_qa",
    "test_v12_ui_report_qa",
]

LEGACY_MODULES = [
    "test_verdict",
    "test_formatters",
    "test_smart_parser",
    "test_powershell_runner",
    "test_report",
    "test_volume_and_events",
    "test_autostart",
    "test_nvme_health",
    "test_v11_grades",
    "test_v11_tray_offscreen",
    "test_v11_autostart_real",  # 已知假失败，特殊判定
    "test_v11_detect_e2e_offscreen",
    "test_v11_metrics_real",
]

_KNOWN_FALSE_FAIL = {"test_v11_autostart_real"}

_RESULT_RE = re.compile(r"通过\s*(\d+)\s*/\s*失败\s*(\d+)")


def _run_module(name: str) -> tuple[int, int, int, str]:
    proc = subprocess.run(  # noqa: S603 - 固定可信解释器
        [PYTHON, os.path.join(TEST_DIR, f"{name}.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=900, cwd=TEST_DIR,
    )
    return proc.returncode, *_parse_counts(proc.stdout + proc.stderr), proc.stdout + proc.stderr


def _parse_counts(output: str) -> tuple[int, int]:
    passed = failed = 0
    for match in _RESULT_RE.finditer(output):
        passed += int(match.group(1))
        failed += int(match.group(2))
    return passed, failed


def _run_selftest() -> bool:
    proc = subprocess.run(  # noqa: S603
        [PYTHON, os.path.join(TEST_DIR, "..", "src", "main.py"), "--selftest"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=os.path.join(TEST_DIR, "..", "src"),
    )
    print(f"main.py --selftest 退出码 {proc.returncode}")
    if proc.returncode != 0:
        print((proc.stdout + proc.stderr)[-2000:])
    return proc.returncode == 0


def _run_smoke() -> bool:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(  # noqa: S603
        [PYTHON, os.path.join(TEST_DIR, "..", "src", "main.py"), "--smoke"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, env=env, cwd=os.path.join(TEST_DIR, "..", "src"),
    )
    print(f"main.py --smoke 退出码 {proc.returncode}")
    if proc.returncode != 0:
        print((proc.stdout + proc.stderr)[-2000:])
    return proc.returncode == 0


def _autostart_real_ok(output: str) -> bool:
    """已知假失败判定：无 FAIL/ERROR 用例且无快捷方式残留即通过。"""
    if "[FAIL]" in output or "[ERROR]" in output:
        return False
    if "残留" in output and "无残留" not in output:
        return False
    return True


def main() -> int:
    grand_passed = grand_failed = 0
    failed_modules: list[str] = []
    started = time.perf_counter()

    # 预检：托盘/单实例相关测试要求无 DiskGuard.exe 占用命名管道
    probe = subprocess.run(  # noqa: S603
        ["tasklist", "/FI", "IMAGENAME eq DiskGuard.exe"],
        capture_output=True, text=True, timeout=30,
    )
    if "DiskGuard.exe" in (probe.stdout or ""):
        print("!! 检测到正在运行的 DiskGuard.exe，请先关闭后再跑回归（影响托盘单实例用例）")
        return 2

    for name in QA_V12_MODULES + LEGACY_MODULES:
        print(f"\n########## {name} ##########")
        try:
            code, passed, failed, output = _run_module(name)
        except subprocess.TimeoutExpired:
            print("[超时] 模块 900s 未完成")
            failed_modules.append(name)
            grand_failed += 1
            continue
        grand_passed += passed
        grand_failed += failed
        tail = "\n".join(output.strip().splitlines()[-3:])
        print(tail)
        if code != 0:
            if name in _KNOWN_FALSE_FAIL and _autostart_real_ok(output):
                print(f"[注] {name} 模块退出码 {code}，但用例全部 PASS 且无残留 -> v1.1 已知假失败，视为通过")
            else:
                failed_modules.append(name)

    selftest_ok = _run_selftest()
    smoke_ok = _run_smoke()
    if not selftest_ok:
        failed_modules.append("main.py --selftest")
    if not smoke_ok:
        failed_modules.append("main.py --smoke")

    elapsed = time.perf_counter() - started
    print("\n" + "=" * 60)
    print(
        f"v1.2 QA 总回归：用例 {grand_passed + grand_failed}，通过 {grand_passed}，"
        f"失败 {grand_failed}，selftest={'OK' if selftest_ok else 'FAIL'}，"
        f"smoke={'OK' if smoke_ok else 'FAIL'}，耗时 {elapsed:.1f}s"
    )
    if failed_modules:
        print(f"失败模块：{failed_modules}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
