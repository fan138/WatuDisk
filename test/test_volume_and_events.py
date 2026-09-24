# -*- coding: utf-8 -*-
"""volume_check._parse_dirty_output 与 event_scan.match_events_to_disk 独立单元测试。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core.event_scan import match_events_to_disk  # noqa: E402
from core.volume_check import _parse_dirty_output  # noqa: E402

# ---------------------------------------------------------------------------
# fsutil dirty query 双语输出解析
# ---------------------------------------------------------------------------


def test_dirty_en_clean():
    assert _parse_dirty_output("Volume - C: is NOT Dirty") is False


def test_dirty_en_dirty():
    assert _parse_dirty_output("Volume - C: is Dirty") is True


def test_dirty_zh_clean():
    assert _parse_dirty_output("卷 - C: 没有设置损坏位。") is False


def test_dirty_zh_dirty():
    assert _parse_dirty_output("卷 - C: 已设置损坏位。") is True


def test_dirty_zh_variant_not_set():
    assert _parse_dirty_output("卷 - C: 未设置损坏位") is False
    assert _parse_dirty_output("卷 - C: 未损坏") is False


def test_dirty_zh_real_world_wording():
    """真机 fsutil 实际输出「卷 - C: 没有损坏」（无「损坏位」三字），仍须判为干净。"""
    assert _parse_dirty_output("卷 - C: 没有损坏") is False


def test_dirty_empty_string():
    assert _parse_dirty_output("") is False


def test_dirty_garbage():
    assert _parse_dirty_output("@@@ random noise ###") is False


def test_dirty_not_substring_guard():
    """「is NOT Dirty」不能因包含子串「is Dirty」而误判为脏。"""
    assert _parse_dirty_output("Volume - C: is NOT Dirty\r\n") is False


# ---------------------------------------------------------------------------
# 事件归因匹配
# ---------------------------------------------------------------------------

DISK = {
    "device_id": "0",
    "model": "WDC WD10EZEX-08WN4A0",
    "bus_type": "SATA",
    "media_type": "HDD",
    "size": 1000 * 1024 ** 3,
    "serial": "WD-WCC6Y4PPXX2X",
}


def _ev(message: str, time: str = "2025-01-01 10:00") -> dict:
    return {"time": time, "provider": "disk", "level": 2, "level_text": "错误", "message": message}


def test_match_harddisk0():
    count, recent = match_events_to_disk([_ev(r"设备 \Device\Harddisk0\DR0 存在坏块。")], DISK)
    assert count == 1 and len(recent) == 1


def test_match_harddisk0_not_harddisk01():
    """Harddisk0 不应吞并 Harddisk01 的消息。"""
    count, _ = match_events_to_disk([_ev(r"\Device\Harddisk01\DR1 bad block")], DISK)
    assert count == 0, "Harddisk01 不应归因到 device_id=0"


def test_match_harddisk0_matches_harddisk0_trailing_slash():
    count, _ = match_events_to_disk([_ev(r"\Device\Harddisk0" + "\\")], DISK)
    assert count == 1


def test_match_by_model():
    count, _ = match_events_to_disk([_ev("The device WDC WD10EZEX-08WN4A0 has a bad block.")], DISK)
    assert count == 1


def test_match_by_model_ignores_short_model():
    """型号过短（<6 字符）不参与模糊匹配，避免误归因。"""
    short_disk = dict(DISK, model="Disk")
    count, _ = match_events_to_disk([_ev("error on Disk subsystem")], short_disk)
    assert count == 0


def test_match_by_serial():
    count, _ = match_events_to_disk([_ev(" failing disk WD-WCC6Y4PPXX2X reported error")], DISK)
    assert count == 1


def test_no_match_unrelated_event():
    count, _ = match_events_to_disk([_ev("Application error in svchost.exe")], DISK)
    assert count == 0 and not _


def test_recent_capped_at_5():
    events = [_ev(r"\Device\Harddisk0\DR0 error", time=f"t{i}") for i in range(20)]
    count, recent = match_events_to_disk(events, DISK)
    assert count == 20
    assert len(recent) == 5


def test_match_none_inputs():
    count, recent = match_events_to_disk([_ev("nothing here")], {"device_id": "", "model": "", "serial": ""})
    assert count == 0 and recent == []


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
