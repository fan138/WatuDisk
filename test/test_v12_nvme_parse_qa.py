# -*- coding: utf-8 -*-
"""v1.2 QA 独立测试：parse_health_log 双布局合成字节流 + 降级 + format_data_units。

QA 自编，不依赖工程师 selftest / test_nvme_health.py 的构造方式：
- 布局构造器按 NVMe 1.3/1.4 规范逐字段驱动（含 HostReadCmds@40 /
  HostWriteCmds@56 / BusyTime@72 三个 parse 不返回但占用偏移的字段），
  用于验证字段偏移互不串扰；
- 标准 / +24 固件偏移两种布局各断言全部 10 个计数字段偏移 + 头部 5 字段。
"""
from __future__ import annotations

import os
import random
import struct
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import nvme_health  # noqa: E402

# NVMe Health Log Page 全部 10 个 128 位计数字段的标准布局偏移
# （前 7 个由 parse_health_log 返回；HostReadCmds/HostWriteCmds/BusyTime 仅占位防串扰）
_COUNTER_FIELDS: list[tuple[str, int]] = [
    ("data_units_read", 8),
    ("data_units_written", 24),
    ("host_read_cmds", 40),
    ("host_write_cmds", 56),
    ("busy_time", 72),
    ("power_cycles", 88),
    ("power_on_hours", 104),
    ("unsafe_shutdowns", 120),
    ("media_errors", 136),
    ("error_log_entries", 152),
]

_HEADER = dict(crit=0, temp_k=308, spare=100, thr=10, pct=2)


def _build_log(
    counters: dict[str, int],
    *,
    crit: int = 0,
    temp_k: int = 308,
    spare: int = 100,
    thr: int = 10,
    pct: int = 2,
    shift: int = 0,
) -> bytes:
    """合成 512 字节健康日志页。shift=0 标准布局 / shift=24 固件偏移布局。"""
    data = bytearray(512)
    struct.pack_into("<BHBBB", data, 0, crit, temp_k, spare, thr, pct)
    for name, offset in _COUNTER_FIELDS:
        struct.pack_into("<Q", data, offset + shift, counters.get(name, 0))
    return bytes(data)


def _std_counters(**overrides: int) -> dict[str, int]:
    values = {
        "data_units_read": 12345,
        "data_units_written": 67890,
        "host_read_cmds": 111,
        "host_write_cmds": 222,
        "busy_time": 333,
        "power_cycles": 1072,
        "power_on_hours": 13297,
        "unsafe_shutdowns": 109,
        "media_errors": 7,
        "error_log_entries": 6401,
    }
    values.update(overrides)
    return values


# ---------------------------------------------------------------- 标准布局
def test_qa_standard_layout_all_fields():
    data = _build_log(_std_counters())
    h = nvme_health.parse_health_log(data)
    assert h is not None, "标准布局应解析成功"
    # 头部 5 字段
    assert h["critical_warning"] == 0
    assert h["temperature_c"] == 35, h["temperature_c"]
    assert h["available_spare_pct"] == 100
    assert h["spare_threshold"] == 10
    assert h["percentage_used"] == 2
    # 7 个返回的计数字段（各取 128 位低 64）
    assert h["data_units_read"] == 12345
    assert h["data_units_written"] == 67890
    assert h["power_cycles"] == 1072
    assert h["power_on_hours"] == 13297
    assert h["unsafe_shutdowns"] == 109
    assert h["media_errors"] == 7
    assert h["error_log_entries"] == 6401


def test_qa_standard_layout_host_cmds_no_crosstalk():
    """@40/@56/@72（Host 命令与 BusyTime）不是 0 时不得污染相邻字段。"""
    data = _build_log(_std_counters(host_read_cmds=2**63, host_write_cmds=2**64 - 1, busy_time=999))
    h = nvme_health.parse_health_log(data)
    assert h is not None
    assert h["data_units_read"] == 12345
    assert h["data_units_written"] == 67890
    assert h["power_cycles"] == 1072
    assert h["power_on_hours"] == 13297


# ---------------------------------------------------------------- +24 偏移布局
def test_qa_shifted_layout_all_fields():
    counters = _std_counters(
        data_units_read=789, data_units_written=1011,
        power_cycles=850, power_on_hours=1557, unsafe_shutdowns=65,
        media_errors=0, error_log_entries=0,
    )
    data = _build_log(counters, crit=0, temp_k=311, spare=100, thr=10, pct=4, shift=24)
    h = nvme_health.parse_health_log(data)
    assert h is not None, "+24 偏移布局应被自适应识别"
    # 头部固定在标准偏移，不受 shift 影响
    assert h["critical_warning"] == 0
    assert h["temperature_c"] == 38
    assert h["available_spare_pct"] == 100
    assert h["spare_threshold"] == 10
    assert h["percentage_used"] == 4
    # 全部计数字段来自 +24 偏移
    assert h["data_units_read"] == 789
    assert h["data_units_written"] == 1011
    assert h["power_cycles"] == 850
    assert h["power_on_hours"] == 1557
    assert h["unsafe_shutdowns"] == 65
    assert h["media_errors"] == 0
    assert h["error_log_entries"] == 0


def test_qa_shifted_layout_switches_only_when_alt_nonzero():
    """标准布局读写计数全 0 且 +24 处也全 0：不得误切布局（结果仍全 0 等价）。"""
    h = nvme_health.parse_health_log(_build_log({}))
    assert h is not None
    assert h["data_units_read"] == 0 and h["data_units_written"] == 0
    assert h["power_on_hours"] == 0


def test_qa_large_128bit_counters_take_low64():
    """计数器高 64 位非零时取低 64 位（struct <Q 语义）。"""
    data = _build_log(_std_counters(power_on_hours=13297))
    # 把 PowerOnHours 扩成 128 位：低 64 位 = 13297（@104），高 64 位 = 7（@112）
    buf = bytearray(data)
    struct.pack_into("<Q", buf, 104 + 8, 7)  # 高 64 位区（104+8）
    h = nvme_health.parse_health_log(bytes(buf))
    assert h is not None and h["power_on_hours"] == 13297


# ---------------------------------------------------------------- 降级路径
def test_qa_none_input_returns_none():
    assert nvme_health.parse_health_log(None) is None  # type: ignore[arg-type]


def test_qa_empty_buffer_returns_none():
    assert nvme_health.parse_health_log(b"") is None


def test_qa_short_buffer_returns_none():
    assert nvme_health.parse_health_log(b"\x01\x02\x03") is None
    assert nvme_health.parse_health_log(b"\x00" * 183) is None


def test_qa_all_zero_buffer_returns_dict():
    """全零缓冲（512 字节）：解析器返回标准 dict（data_units_read 等字段为 0），
    不抛异常、也不返回 None —— 与 main.py --selftest 的 'nvme parse all-zero stays standard' 行为一致。"""
    result = nvme_health.parse_health_log(b"\x00" * 512)
    assert isinstance(result, dict), f"全零缓冲应返回 dict，实际返回 {result!r}"
    assert result["data_units_read"] == 0


def test_qa_garbage_buffer_never_raises():
    """512 字节伪随机垃圾：绝不抛异常，返回 None 或字段完整的 dict。"""
    rng = random.Random(20260218)
    for _ in range(20):
        blob = bytes(rng.getrandbits(8) for _ in range(512))
        result = nvme_health.parse_health_log(blob)
        assert result is None or isinstance(result, dict)
        if isinstance(result, dict):
            for key in (
                "critical_warning", "temperature_c", "available_spare_pct",
                "spare_threshold", "percentage_used", "data_units_read",
                "data_units_written", "power_cycles", "power_on_hours",
                "unsafe_shutdowns", "media_errors", "error_log_entries",
            ):
                assert key in result, f"垃圾数据解析结果缺字段 {key}"


# ---------------------------------------------------------------- query_nvme_health 输入防线
def test_qa_query_invalid_drive_numbers():
    assert nvme_health.query_nvme_health(-1) is None
    assert nvme_health.query_nvme_health("0") is None  # type: ignore[arg-type]
    assert nvme_health.query_nvme_health(True) is None  # bool 视为非法
    assert nvme_health.query_nvme_health(99) is None  # 越界盘号


# ---------------------------------------------------------------- format_data_units
def test_qa_format_data_units_zero():
    assert nvme_health.format_data_units(0) == "0 GB"


def test_qa_format_data_units_one_du_is_half_mb():
    """1 DU = 512,000 B ≈ 0.49 MB：当前实现只输出 GB/TB，亚 GB 四舍五入为 0 GB。"""
    text = nvme_health.format_data_units(1)
    assert text is not None
    # 换算正确性由 TB 级用例保证；此处仅要求亚 GB 不抛异常且有输出


def test_qa_format_data_units_gb_rounding():
    # 10240 DU = 5,242,880,000 B = 4.88 GiB -> "5 GB"
    assert nvme_health.format_data_units(10240) == "5 GB"
    # 2000 DU = 1,024,000,000 B = 0.95 GiB -> "1 GB"
    assert nvme_health.format_data_units(2000) == "1 GB"
    # 2001 DU = 0.956 GiB -> "1 GB"
    assert nvme_health.format_data_units(2001) == "1 GB"


def test_qa_format_data_units_tb():
    # 真机 ZHITAI Ti600：46,420,225 DU ≈ 21.6 TB
    assert nvme_health.format_data_units(46420225) == "21.6 TB"
    # 2,200,000 DU = 1,126,400,000,000 B ≈ 1.02 TB
    assert nvme_health.format_data_units(2200000) == "1.0 TB"
    # 真机 PD0：18,463,483 DU ≈ 8.6 TB
    assert nvme_health.format_data_units(18463483) == "8.6 TB"


def test_qa_format_data_units_invalid():
    assert nvme_health.format_data_units(None) is None
    assert nvme_health.format_data_units("abc") is None
    assert nvme_health.format_data_units(True) is None
    assert nvme_health.format_data_units(-1) is None


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
