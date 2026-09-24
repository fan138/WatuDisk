# -*- coding: utf-8 -*-
"""smart_parser.parse_vendor_attributes 独立单元测试。

覆盖边界：
- 手工构造 362 字节合成数据（2 字节版本号 + 30 个 12 字节属性），
  含 05 / C5 / C6 / C7 关键属性与多字节原始值；
- 属性表以 0x00 结尾（提前终止）；
- 截断数据（不足 14 字节 / 属性块不完整）；
- 全零数据；垃圾数据；None / 非法元素输入。
全部要求：不崩溃、失败时返回空列表。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import smart_parser  # noqa: E402


def make_attr_block(attr_id: int, value: int, raw: int, flags: int = 0) -> list[int]:
    """构造一个 12 字节 SMART 属性结构。"""
    return [attr_id & 0xFF, flags & 0xFF, (flags >> 8) & 0xFF, value & 0xFF, value & 0xFF] + list(
        raw.to_bytes(6, "little")
    ) + [0x00]


def make_vendor(attr_blocks: list[list[int]], version: list[int] | None = None) -> list[int]:
    """2 字节版本号 + 若干属性块。"""
    return (version if version is not None else [0x01, 0x00]) + [b for block in attr_blocks for b in block]


def test_full_362_byte_synthetic_data():
    """2 + 30*12 = 362 字节，最后一属性后余量用 0x00 填充（终止符在尾部）。"""
    key_raws = {0x05: 4, 0xC5: 8, 0xC6: 2, 0xC7: 17}
    blocks = [make_attr_block(aid, 100, raw) for aid, raw in key_raws.items()]
    # 补充普通属性直到 30 个
    filler_ids = [0x01, 0x07, 0x09, 0x0C, 0xAA, 0xC2]
    blocks += [make_attr_block(fid, 200, 123456 + fid) for fid in filler_ids]
    blocks += [make_attr_block((0x10 + i) & 0xFF, 50, i) for i in range(30 - len(blocks))]
    vendor = make_vendor(blocks)
    assert len(vendor) == 362, f"合成数据应 362 字节，实际 {len(vendor)}"
    attrs = smart_parser.parse_vendor_attributes(vendor)
    assert len(attrs) == 30, f"应解析出 30 个属性，实际 {len(attrs)}"
    by_id = {a["id"]: a for a in attrs}
    for aid, raw in key_raws.items():
        assert by_id[aid]["raw"] == raw, f"属性 0x{aid:02X} 原始值应为 {raw}，实际 {by_id[aid]['raw']}"
        assert by_id[aid]["value"] == 100
        assert by_id[aid]["hex"] == f"0x{aid:02X}"
    assert by_id[0x05]["name"] == "重映射扇区数"
    assert by_id[0xC5]["name"] == "待映射扇区数"
    assert by_id[0xC6]["name"] == "无法修正扇区数"
    assert by_id[0xC7]["name"] == "接口传输错误（CRC）"
    assert by_id[0xC2]["name"] == "温度"


def test_multibyte_little_endian_raw():
    """原始值 0x010203040506 按小端 6 字节还原。"""
    vendor = make_vendor([make_attr_block(0x09, 100, 0x010203040506)])
    attrs = smart_parser.parse_vendor_attributes(vendor)
    assert len(attrs) == 1
    assert attrs[0]["raw"] == 0x010203040506


def test_attr_terminator_stops_parsing():
    """属性 ID 为 0 表示表结束，其后的数据不应被解析。"""
    vendor = make_vendor(
        [make_attr_block(0x05, 100, 7)] + [[0x00] * 12] + [make_attr_block(0xC6, 100, 9)]
    )
    attrs = smart_parser.parse_vendor_attributes(vendor)
    assert len(attrs) == 1
    assert attrs[0]["id"] == 0x05 and attrs[0]["raw"] == 7


def test_truncated_below_minimum_returns_empty():
    assert smart_parser.parse_vendor_attributes([]) == []
    assert smart_parser.parse_vendor_attributes([0x01]) == []  # 仅 1 字节
    assert smart_parser.parse_vendor_attributes([0x01, 0x00]) == []  # 仅版本号
    assert smart_parser.parse_vendor_attributes([0x01, 0x00] + [0x05] * 11) == []  # 13 字节 < 14


def test_truncated_partial_attr_block_keeps_complete_ones():
    """版本号 + 1.5 个属性块：只解析出完整的 1 个。"""
    vendor = make_vendor([make_attr_block(0x05, 100, 3)]) + [0xC5, 0x00, 0x00, 0x64, 0x64, 0x01]
    attrs = smart_parser.parse_vendor_attributes(vendor)
    assert len(attrs) == 1
    assert attrs[0]["id"] == 0x05


def test_all_zero_data_returns_empty():
    assert smart_parser.parse_vendor_attributes([0x00] * 362) == []


def test_garbage_data_no_crash():
    """随机垃圾字节：长度足够则解析出若干属性但不崩溃，长度不足返回空。"""
    rng = random.Random(42)
    garbage = [rng.randrange(256) for _ in range(362)]
    attrs = smart_parser.parse_vendor_attributes(garbage)  # 只要不抛异常即通过
    assert isinstance(attrs, list)
    assert smart_parser.parse_vendor_attributes([rng.randrange(256) for _ in range(7)]) == []


def test_none_and_invalid_input_returns_empty():
    assert smart_parser.parse_vendor_attributes(None) == []
    assert smart_parser.parse_vendor_attributes(12345) == []
    assert smart_parser.parse_vendor_attributes("not-bytes") == []
    assert smart_parser.parse_vendor_attributes([1, "x", 3] + [0] * 20) == []  # 非法元素 -> 整体降级
    assert smart_parser.parse_vendor_attributes([-1, 256, 999]) == []  # 越界值被 &0xFF 归一，14 字节内无有效属性


def test_bytes_object_input():
    """直接传 bytes 对象也应可解析。"""
    vendor = bytes(make_vendor([make_attr_block(0xC6, 100, 2)]))
    attrs = smart_parser.parse_vendor_attributes(vendor)
    assert len(attrs) == 1
    assert attrs[0]["raw"] == 2


def test_unknown_attr_gets_hex_placeholder_name():
    vendor = make_vendor([make_attr_block(0xFE, 100, 1)])
    attrs = smart_parser.parse_vendor_attributes(vendor)
    assert attrs[0]["name"] == "未知属性 0xFE"


def test_attr_display_name_known_and_unknown():
    assert smart_parser.attr_display_name(0xC5) == "待映射扇区数"
    assert smart_parser.attr_display_name(0x99).startswith("未知属性")


def test_fetch_raw_records_graceful_without_admin():
    """真机调用（可能非管理员）：必须返回 list 且不抛异常。"""
    records = smart_parser.fetch_raw_records()
    assert isinstance(records, list)
    for record in records:
        assert isinstance(record, dict)
        assert isinstance(record.get("attrs"), list)


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
