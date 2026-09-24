# -*- coding: utf-8 -*-
"""disk_info.format_size / format_hours 独立单元测试。

覆盖边界：0、None、负数、B 级、GB 级、TB 级；小时 0 / 负数 / 非法 / 跨年阈值。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core.disk_info import format_hours, format_size  # noqa: E402

GB = 1024 ** 3
TB = 1024 ** 4


def test_size_zero():
    assert format_size(0) == "未知容量"


def test_size_none():
    assert format_size(None) == "未知容量"


def test_size_negative():
    assert format_size(-1024) == "未知容量"


def test_size_byte_level():
    # B 级数据折算后不足 1 GB，按实现显示 "0 GB"
    assert format_size(100) == "0 GB"


def test_size_1gb():
    assert format_size(GB) == "1 GB"


def test_size_512gb():
    assert format_size(512 * GB) == "512 GB"


def test_size_2tb():
    assert format_size(2 * TB) == "2.00 TB"


def test_size_1tb_boundary():
    assert format_size(TB) == "1.00 TB"


def test_size_just_below_1tb_still_gb():
    assert format_size(TB - 1).endswith("GB")


def test_hours_none():
    assert format_hours(None) is None


def test_hours_invalid_string():
    assert format_hours("abc") is None


def test_hours_negative():
    assert format_hours(-5) is None


def test_hours_small():
    assert format_hours(0) == "0 小时"
    assert format_hours(36) == "36 小时"


def test_hours_thousands_separator():
    assert format_hours(9000).startswith("9,000 小时")


def test_hours_one_year_boundary():
    assert format_hours(8760) == "8,760 小时（约 1.0 年）"
    assert format_hours(8759) == "8,759 小时"  # 未满一年不附年份


def test_hours_pro_year_format():
    """v1.1 专业指标格式：「14,200 小时 · 约 1.6 年」。"""
    from core.disk_info import format_hours_pro

    assert format_hours_pro(14200) == "14,200 小时 · 约 1.6 年"
    assert format_hours_pro(8760) == "8,760 小时 · 约 1.0 年"
    assert format_hours_pro(8759) == "8,759 小时"  # 未满一年不附年份
    assert format_hours_pro(None) is None
    assert format_hours_pro(-1) is None


def test_format_int_thousand_separator():
    """v1.1 千分位格式化；None / 非法值返回 None（界面显示「—」）。"""
    from core.disk_info import format_int

    assert format_int(14200) == "14,200"
    assert format_int(0) == "0"
    assert format_int(None) is None
    assert format_int("abc") is None
    assert format_int(True) is None


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
