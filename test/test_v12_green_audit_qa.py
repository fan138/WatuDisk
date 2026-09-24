# -*- coding: utf-8 -*-
"""v1.2 QA 独立测试：绿色版合规静态审计。

规则：src/ 全部应用代码禁止 socket / urllib / requests / winreg 导入（离线、
不写注册表），禁止 PIL 导入。
"""
from __future__ import annotations

import os
import re
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.normpath(os.path.join(TEST_DIR, "..", "src"))

_BANNED = ("socket", "urllib", "requests", "winreg", "PIL")
_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", re.MULTILINE)


def _app_sources() -> list[str]:
    hits: list[str] = []
    for root, dirs, files in os.walk(SRC_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                hits.append(os.path.join(root, name))
    return hits


def test_qa_green_no_banned_imports():
    offenders: list[str] = []
    for path in _app_sources():
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for match in _IMPORT_RE.finditer(source):
            root_module = match.group(1).split(".")[0]
            if root_module in _BANNED:
                offenders.append(f"{path}: {match.group(0).strip()}")
    assert not offenders, f"应用代码出现禁用导入：\n" + "\n".join(offenders)


def test_qa_green_version_is_v12():
    import importlib.util

    spec = importlib.util.spec_from_file_location("dg_main", os.path.join(SRC_DIR, "main.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.APP_VERSION == "v1.2", module.APP_VERSION
    assert module.APP_NAME == "硬盘健康卫士"


def test_qa_report_version_is_v12():
    src_report = os.path.join(SRC_DIR, "core", "report.py")
    with open(src_report, encoding="utf-8") as handle:
        source = handle.read()
    assert 'APP_VERSION = "v1.2"' in source, "report.py 版本号应为 v1.2"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
