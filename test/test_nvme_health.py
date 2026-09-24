# -*- coding: utf-8 -*-
"""v1.2 NVMe 健康日志直读单元测试（合成字节流，无需管理员 / 真机）。"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import nvme_health  # noqa: E402


def _mk_health_log(
    du_read: int,
    du_written: int,
    power_cycles: int = 1072,
    poh: int = 13296,
    unsafe: int = 88,
    media: int = 0,
    crit: int = 0,
    temp_k: int = 308,
    spare: int = 100,
    spare_thr: int = 10,
    pct: int = 2,
    shift: int = 0,
) -> bytes:
    """构造合成 512 字节健康日志页（shift=0 标准 / shift=24 固件偏移布局）。"""
    data = bytearray(512)
    struct.pack_into("<BHBBB", data, 0, crit, temp_k, spare, spare_thr, pct)
    struct.pack_into("<Q", data, 8 + shift, du_read)
    struct.pack_into("<Q", data, 24 + shift, du_written)
    struct.pack_into("<Q", data, 88 + shift, power_cycles)
    struct.pack_into("<Q", data, 104 + shift, poh)
    struct.pack_into("<Q", data, 120 + shift, unsafe)
    struct.pack_into("<Q", data, 136 + shift, media)
    struct.pack_into("<Q", data, 152 + shift, 3)
    return bytes(data)


def test_parse_standard_layout():
    h = nvme_health.parse_health_log(_mk_health_log(123, 456))
    assert h is not None
    assert h["critical_warning"] == 0
    assert h["temperature_c"] == 35
    assert h["available_spare_pct"] == 100
    assert h["spare_threshold"] == 10
    assert h["percentage_used"] == 2
    assert h["data_units_read"] == 123
    assert h["data_units_written"] == 456
    assert h["power_cycles"] == 1072
    assert h["power_on_hours"] == 13296
    assert h["unsafe_shutdowns"] == 88
    assert h["media_errors"] == 0
    assert h["error_log_entries"] == 3


def test_parse_shifted_layout():
    """固件怪癖布局：字段整体 +24 偏移，自适应应能解析出正确值。"""
    h = nvme_health.parse_health_log(
        _mk_health_log(789, 1011, power_cycles=65, poh=1556, unsafe=7, shift=24)
    )
    assert h is not None
    assert h["data_units_read"] == 789
    assert h["data_units_written"] == 1011
    assert h["power_cycles"] == 65
    assert h["power_on_hours"] == 1556
    assert h["unsafe_shutdowns"] == 7
    # 头部字段两种布局固定标准偏移
    assert h["temperature_c"] == 35
    assert h["percentage_used"] == 2


def test_parse_all_zero_stays_standard():
    """标准布局计数全 0 且 +24 处也全 0：不误切布局。"""
    h = nvme_health.parse_health_log(_mk_health_log(0, 0))
    assert h is not None
    assert h["data_units_read"] == 0 and h["data_units_written"] == 0


def test_parse_degrades_on_bad_input():
    assert nvme_health.parse_health_log(b"") is None
    assert nvme_health.parse_health_log(None) is None
    assert nvme_health.parse_health_log(b"\x01" * 100) is None


def test_query_nvme_health_never_raises():
    """非 NVMe / 越界盘号 / 非法输入一律返回 None（不抛异常）。"""
    assert nvme_health.query_nvme_health(-1) is None
    assert nvme_health.query_nvme_health("abc") is None
    assert nvme_health.query_nvme_health(True) is None
    assert nvme_health.query_nvme_health(99) is None  # 不存在的物理盘


def test_format_data_units():
    # 46420225 DU * 512000 B ≈ 21.6 TB（1024 进制，真机 ZHITAI Ti600 实测值）
    assert nvme_health.format_data_units(46420225) == "21.6 TB"
    # 10240 DU = 5,242,880,000 B ≈ 4.88 GB -> "5 GB"
    assert nvme_health.format_data_units(10240) == "5 GB"
    assert nvme_health.format_data_units(0) == "0 GB"
    assert nvme_health.format_data_units(None) is None
    assert nvme_health.format_data_units("abc") is None
    assert nvme_health.format_data_units(True) is None
    assert nvme_health.format_data_units(-1) is None


def test_layout_constants_consistent():
    """+24 偏移布局应严格等于标准布局逐字段 +24。"""
    for key, offset in nvme_health._LAYOUT_STD.items():
        assert nvme_health._LAYOUT_SHIFTED[key] == offset + 24, key


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
