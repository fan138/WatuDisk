# -*- coding: utf-8 -*-
"""Store 体检记录删除接口单元测试（v1.2.1）。

使用临时目录注入 dir_override，绝不写用户真实数据；测完清理。
store.py 仅依赖标准库，本测试无需 PySide / Qt。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core.store import Store  # noqa: E402


def _make_store() -> tuple[Store, str]:
    tmp = tempfile.mkdtemp(prefix="diskguard_test_store_")
    return Store(tmp), tmp


def _seed(store: Store, n: int) -> None:
    for i in range(n):
        store.append_history({"time": f"2026-10-{i:02d}", "text": f"rec{i}", "level": "ok"})


def test_clear_history_removes_all():
    store, tmp = _make_store()
    try:
        _seed(store, 5)
        assert len(store.history()) == 5
        cleared = store.clear_history()
        assert cleared == 5
        assert store.history() == []
        # 再次清空应为 0（幂等）
        assert store.clear_history() == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_delete_history_at_removes_one():
    store, tmp = _make_store()
    try:
        _seed(store, 3)
        # 删除最新（index 0）后，原 index1 升到 0
        assert store.delete_history_at(0) is True
        hist = store.history()
        assert len(hist) == 2
        assert {h["text"] for h in hist} == {"rec1", "rec0"}
        # 越界删除返回 False
        assert store.delete_history_at(99) is False
        assert store.delete_history_at(-1) is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_clear_persists_to_disk():
    store, tmp = _make_store()
    try:
        _seed(store, 4)
        store.clear_history()
        # 重新从磁盘加载，确认确实清空（不是仅内存清空）
        reopened = Store(tmp)
        assert reopened.history() == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
