# -*- coding: utf-8 -*-
"""极简测试运行器：收集当前模块内所有 test_* 函数并逐个执行。

pytest 不可用时的替代方案。用法：
    from _runner import run_module_tests
    run_module_tests(__name__)
"""
from __future__ import annotations

import importlib
import sys
import time
import traceback


def run_module_tests(module_name: str) -> int:
    """运行模块内全部 test_* 函数。全部通过返回 0，否则返回 1。"""
    module = importlib.import_module(module_name)
    tests = sorted(
        (name, func)
        for name, func in vars(module).items()
        if name.startswith("test_") and callable(func)
    )
    passed: list[str] = []
    failed: list[str] = []
    started = time.perf_counter()
    print(f"\n===== {module_name}：共 {len(tests)} 个用例 =====")
    for name, func in tests:
        try:
            func()
        except AssertionError as exc:
            failed.append(name)
            print(f"[FAIL] {name}")
            if str(exc):
                print(f"       -> {exc}")
        except Exception:  # noqa: BLE001 - 测试运行器需要捕获一切以继续
            failed.append(name)
            print(f"[ERROR] {name}")
            traceback.print_exc()
        else:
            passed.append(name)
            print(f"[PASS] {name}")
    elapsed = time.perf_counter() - started
    print(f"----- {module_name} 结果：通过 {len(passed)} / 失败 {len(failed)}，耗时 {elapsed:.2f}s -----")
    if failed:
        print(f"失败用例：{failed}")
        return 1
    return 0


def bootstrap_src_path() -> None:
    """把 ../src 加入 sys.path（脚本位于 test/ 目录下的场景）。"""
    import os

    src = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    if src not in sys.path:
        sys.path.insert(0, src)
