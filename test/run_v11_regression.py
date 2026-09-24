# -*- coding: utf-8 -*-
"""v1.1 QA 总回归编排器：跑全部既有 + v1.1 新增测试文件，输出汇总。"""
from __future__ import annotations

import os
import subprocess
import sys
import time

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

# 既有 v1.0 资产 + v1.1 QA 新增 + v1.2 新增
MODULES = [
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
    "test_v11_autostart_real",
    "test_v11_detect_e2e_offscreen",
    "test_v11_metrics_real",
]


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    grand_passed = 0
    grand_failed = 0
    failed_modules: list[str] = []
    started = time.perf_counter()

    for module in MODULES:
        print(f"\n########## {module} ##########")
        proc = subprocess.run(  # noqa: S603 - 固定可信解释器
            [PYTHON, os.path.join(TEST_DIR, f"{module}.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            cwd=TEST_DIR,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        tail = output.strip().splitlines()[-2:]
        print("\n".join(tail))
        for line in output.splitlines():
            if "结果：通过" in line:
                try:
                    passed, failed = int(line.split("通过")[1].split("/")[0].strip()), int(line.split("/ 失败")[1].split("，")[0].strip())
                except (IndexError, ValueError):
                    passed, failed = 0, 1
                grand_passed += passed
                grand_failed += failed
        if proc.returncode != 0:
            failed_modules.append(module)

    elapsed = time.perf_counter() - started
    print("\n" + "=" * 60)
    print(f"v1.1 总回归：用例 {grand_passed + grand_failed}，通过 {grand_passed}，失败 {grand_failed}，耗时 {elapsed:.1f}s")
    if failed_modules:
        print(f"失败模块：{failed_modules}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
