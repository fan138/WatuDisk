# -*- coding: utf-8 -*-
"""report.py 独立单元测试：HTML 构建 + export_report 写盘（写到临时目录后删除）。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import report  # noqa: E402
from core import verdict  # noqa: E402

DISK = {
    "device_id": "0",
    "model": "Report Test SSD <script>alert(1)</script>",
    "media_type": "SSD",
    "bus_type": "NVMe",
    "health_status": "Healthy",
    "op_status": "OK",
    "size": 512 * 1024 ** 3,
    "serial": "RPT001",
}


def _sample_results() -> list[dict]:
    v_ok = verdict.evaluate_disk(DISK, {"Temperature": 40, "Wear": 5, "PowerOnHours": 9000}, [], 0, [], [])
    v_bad = verdict.evaluate_disk(
        dict(DISK, device_id="1", model="Bad HDD", media_type="HDD", bus_type="SATA", health_status="Unhealthy"),
        {"Temperature": 75, "Wear": None},
        [{"id": 0xC6, "hex": "0xC6", "name": "无法修正扇区数", "value": 1, "raw": 3}],
        10,
        [{"time": "t", "provider": "disk", "level": 2, "level_text": "错误", "message": "坏块"}],
        [{"drive": "C:", "dirty": True, "disk_number": 1}],
    )
    return [
        {
            "disk": DISK,
            "counters": {"Temperature": 40, "Wear": 5, "PowerOnHours": 9000},
            "smart_attrs": [],
            "event_count": 0,
            "event_recent": [],
            "dirty_volumes": [],
            "all_volumes": [],
            "verdict": v_ok,
        },
        {
            "disk": dict(DISK, device_id="1", model="Bad HDD", media_type="HDD", bus_type="SATA"),
            "counters": {"Temperature": 75, "Wear": None},
            "smart_attrs": [{"id": 0xC6, "hex": "0xC6", "name": "无法修正扇区数", "value": 1, "raw": 3}],
            "event_count": 10,
            "event_recent": [{"time": "t", "provider": "disk", "level": 2, "level_text": "错误", "message": "坏块"}],
            "dirty_volumes": [{"drive": "C:", "dirty": True, "disk_number": 1}],
            "all_volumes": [{"drive": "C:", "dirty": True, "disk_number": 1}],
            "verdict": v_bad,
        },
    ]


def test_build_html_contains_key_sections():
    html_text = report.build_report_html(_sample_results())
    for keyword in (
        "挖兔硬盘精灵",
        "检测报告",
        "Report Test SSD",
        "Bad HDD",
        "大白话判读与建议",
        "事件日志（最近 30 天）",
        "卷损坏位与剩余空间",
        "SMART 属性明细",
        "只读",
    ):
        assert keyword in html_text, f"HTML 缺少关键 section: {keyword}"


def test_build_html_escapes_model():
    """型号中的 HTML 特殊字符必须被转义（防注入）。"""
    html_text = report.build_report_html(_sample_results())
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;" in html_text


def test_build_html_summary_line():
    html_text = report.build_report_html(_sample_results())
    assert "共 2 块硬盘" in html_text
    assert "危险" in html_text


def test_build_html_empty_results():
    html_text = report.build_report_html([])
    assert "共 0 块硬盘" in html_text
    assert "挖兔硬盘精灵" in html_text


def test_export_report_roundtrip_and_cleanup():
    """导出到临时目录 -> 内容可读回且含关键 section -> 删除。"""
    tmpdir = tempfile.mkdtemp(prefix="diskguard_qa_")
    path = os.path.join(tmpdir, "report_test.html")
    try:
        ok, error = report.export_report(path, _sample_results())
        assert ok is True, f"export_report 失败: {error}"
        assert error == ""
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        for keyword in ("挖兔硬盘精灵", "大白话判读与建议", "卷损坏位与剩余空间", "只读"):
            assert keyword in content, f"导出报告缺少关键 section: {keyword}"
    finally:
        if os.path.isfile(path):
            os.remove(path)
        os.rmdir(tmpdir)
    assert not os.path.exists(path)


def test_export_report_invalid_path_returns_error_tuple():
    """非法路径：返回 (False, 原因) 而非抛异常。"""
    ok, error = report.export_report("Z:\\not\\exist\\dir\\r.html", _sample_results())
    assert ok is False
    assert error != ""


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
