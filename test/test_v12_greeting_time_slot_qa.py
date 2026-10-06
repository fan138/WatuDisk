# -*- coding: utf-8 -*-
"""v1.2 开机问候「时段串味」回归测试。

坛友反馈：系统时间 14 点（下午），体检后的气泡/报告却显示「夜深了…你也早点休息」。

根因：BOOT_GREETING 列表按时段排列，但 boot_greeting() 用硬编码切片取文案：
早晨 [:7]、午后 [7:14]、夜晚 [14:]。而实际列表里「夜深了」「晚安前的守护」
两条夜晚文案位于索引 11、12，落在 [7:14] 区间内 → 午后被取到夜晚文案。

修复：改用与文案注释区块严格对应的常量切片
（早晨 0:7 / 午后 7:11 / 夜晚 11:），并把傍晚并入白昼（12-18 点）。

本测试通过替换模块内 datetime 逐时段抽样，确保各时段不串味。
"""
from __future__ import annotations

import datetime as _real_datetime
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import tender  # noqa: E402

# 夜晚专属词：出现即说明该时段拿到了夜晚文案
_NIGHT_WORDS = ("夜深", "晚安", "夜色", "守夜人", "早点休息", "好梦", "值岗")
# 早晨专属词
_MORNING_WORDS = ("早上好", "早安", "晨光", "清晨")
# 午后专属词（「傍晚好…守到日落」语义上已入夜，故不列为午后词）
_AFTERNOON_WORDS = ("午后", "下午", "阳光", "新的一天")


class _FakeDatetime:
    """可指定小时数的 datetime.now() 替身。"""

    def __init__(self, hour: int) -> None:
        self._hour = hour

    def now(self):
        return _real_datetime.datetime(2026, 10, 5, self._hour, 30)


def _sample(hour: int, times: int = 200) -> list[str]:
    """在指定小时反复取问候语（调用后恢复原 datetime）。"""
    original = tender.datetime
    tender.datetime = _FakeDatetime(hour)
    try:
        return [tender.boot_greeting() for _ in range(times)]
    finally:
        tender.datetime = original


def _count_with(words: tuple[str, ...], samples: list[str]) -> int:
    return sum(1 for s in samples if any(w in s for w in words))


# ---------------- 各时段不串味 ----------------

def test_afternoon_never_gets_night_text():
    """核心断言：12-17 点（含 14 点）绝不能出现夜晚文案。"""
    for hour in (12, 13, 14, 15, 16, 17):
        samples = _sample(hour)
        night = _count_with(_NIGHT_WORDS, samples)
        assert night == 0, f"{hour} 点出现夜晚文案 {night} 次，例: {[s for s in samples if any(w in s for w in _NIGHT_WORDS)][:2]}"


def test_morning_never_gets_night_text():
    """早晨 5-11 点不应出现夜晚文案。"""
    for hour in (5, 7, 9, 11):
        samples = _sample(hour)
        assert _count_with(_NIGHT_WORDS, samples) == 0, f"{hour} 点出现夜晚文案"


def test_night_never_gets_morning_text():
    """夜晚 18 点后不应出现早晨文案。"""
    for hour in (18, 20, 22, 23):
        samples = _sample(hour)
        assert _count_with(_MORNING_WORDS, samples) == 0, f"{hour} 点出现早晨文案"


def test_small_hours_are_night():
    """凌晨 0-4 点属于夜晚段（boot_greeting 走 else 分支）。"""
    samples = _sample(2)
    assert _count_with(_NIGHT_WORDS, samples) > 0, "凌晨应出现夜晚文案"


# ---------------- 切片常量与文案区块对齐 ----------------

def test_slice_constants_match_comment_blocks():
    """切片常量必须与 BOOT_GREETING 的注释区块严格对齐（防止以后再加文案又错位）。"""
    greetings = tender.BOOT_GREETING
    assert len(greetings) == 20, f"文案数量变化需同步切片常量，当前 {len(greetings)} 条"

    morning = greetings[tender._BOOT_MORNING_SLICE]
    afternoon = greetings[tender._BOOT_AFTERNOON_SLICE]
    night = greetings[tender._BOOT_NIGHT_SLICE]

    # 早晨段不应含夜晚词，夜晚段不应含早晨/午后词
    assert not any(w in s for s in morning for w in _NIGHT_WORDS), "早晨段混入夜晚文案"
    assert not any(w in s for s in afternoon for w in _NIGHT_WORDS), "午后段混入夜晚文案"
    assert not any(w in s for s in night for w in _MORNING_WORDS), "夜晚段混入早晨文案"
    assert not any(w in s for s in night for w in _AFTERNOON_WORDS), "夜晚段混入午后文案"


def test_all_greetings_reachable():
    """三段切片合起来应覆盖全部文案（无遗漏、无重叠）。"""
    covered = (
        len(tender.BOOT_GREETING[tender._BOOT_MORNING_SLICE])
        + len(tender.BOOT_GREETING[tender._BOOT_AFTERNOON_SLICE])
        + len(tender.BOOT_GREETING[tender._BOOT_NIGHT_SLICE])
    )
    assert covered == len(tender.BOOT_GREETING), f"三段合计 {covered} != 总数 {len(tender.BOOT_GREETING)}"


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
