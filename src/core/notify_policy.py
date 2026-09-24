# -*- coding: utf-8 -*-
"""提醒策略（v1.4）：五种提醒方案 + 用户习惯识别降噪。

五种方案（用户可在主界面切换）：
- quiet    安静模式：只报异常（警告/危险/空间告急），健康完成不弹；
- gentle   轻声细语（推荐默认）：健康完成提示每天最多 2 条，异常必报；
- daily    日常陪伴：每次定时/开机体检完成都弹（v1.3 的频率）；
- warm     热情关怀：每次都弹 + 附加温度/空间等当前状态一句；
- extra    高频呵护：每次都弹 + 附加一条「硬盘小知识」；

习惯识别（轻量、纯本地）：
- 连续 4 条「健康完成」气泡用户都没打开过主界面 -> 视为不打扰偏好，
  当天剩余的健康提示自动静默（异常永远照报，且跨天自动重置）；
- 用户打开主界面即视为互动，静默计数清零。
"""
from __future__ import annotations

from datetime import datetime

from core.store import get_store

PROFILE_QUIET = "quiet"
PROFILE_GENTLE = "gentle"
PROFILE_DAILY = "daily"
PROFILE_WARM = "warm"
PROFILE_EXTRA = "extra"

PROFILE_LABELS: dict[str, str] = {
    PROFILE_QUIET: "安静模式 · 只报异常",
    PROFILE_GENTLE: "轻声细语 · 健康提示每日 2 条（推荐）",
    PROFILE_DAILY: "日常陪伴 · 每次体检都提醒",
    PROFILE_WARM: "热情关怀 · 提醒附当前状态",
    PROFILE_EXTRA: "高频呵护 · 提醒附硬盘小知识",
}

PROFILE_ORDER = [PROFILE_QUIET, PROFILE_GENTLE, PROFILE_DAILY, PROFILE_WARM, PROFILE_EXTRA]

IGNORED_STREAK_LIMIT = 4  # 连续 4 条健康气泡无互动 -> 当天健康提示静默

# 硬盘小知识（extra 方案附加，轮换）
TIPS: list[str] = [
    "小知识：SSD 剩余空间保持在 20% 以上，写入寿命会更长。",
    "小知识：每半年看一眼「剩余寿命」，比坏了再补救省心得多。",
    "小知识：关机前让硬盘灯熄灭再拔电源，是最温柔的告别。",
    "小知识：温度每低 10°C，电子元件的老化速度大约减半。",
    "小知识：睡眠模式下的硬盘也在休息，别频繁唤醒它。",
    "小知识：重要数据遵循「3-2-1」：三份拷贝、两种介质、一份异地。",
    "小知识：硬盘最怕的是意外断电，稳压电源是隐形守护者。",
    "小知识：回收站清空前，先想想有没有舍不得的文件。",
    "小知识：机械硬盘怕震，固态硬盘怕热，各有各的脾气。",
    "小知识：定期开机让硬盘活动活动，也是一种保养。",
]

TODAY_KEY = "notify_counters_date"
SHOWN_KEY = "notify_healthy_shown"
STREAK_KEY = "notify_ignored_streak"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _counters(store) -> dict:
    """读取（并按日重置）提醒计数器。"""
    today = _today()
    if str(store.get_setting(TODAY_KEY) or "") != today:
        store.set_setting(TODAY_KEY, today)
        store.set_setting(SHOWN_KEY, 0)
        store.set_setting(STREAK_KEY, 0)
    return {
        "shown": int(store.get_setting(SHOWN_KEY) or 0),
        "streak": int(store.get_setting(STREAK_KEY) or 0),
    }


def mark_interacted() -> None:
    """用户打开主界面 -> 互动，静默计数清零（习惯识别的「正反馈」）。"""
    store = get_store()
    _counters(store)  # 确保按日重置
    store.set_setting(STREAK_KEY, 0)


def should_notify_healthy(profile: str) -> bool:
    """判断「体检全部健康」是否应该弹气泡（异常/空间告急不受此限制）。"""
    store = get_store()
    if not bool(store.get_setting("notify_enabled", True)):
        return False
    counters = _counters(store)
    if counters["streak"] >= IGNORED_STREAK_LIMIT:
        return False  # 习惯识别：连续忽略 -> 当天健康提示静默
    caps = {
        PROFILE_QUIET: 0,
        PROFILE_GENTLE: 2,
        PROFILE_DAILY: 99,
        PROFILE_WARM: 99,
        PROFILE_EXTRA: 99,
    }
    return counters["shown"] < caps.get(profile, 99)


def mark_healthy_notified(profile: str) -> None:
    """记录一条健康气泡已弹出。"""
    store = get_store()
    counters = _counters(store)
    store.set_setting(SHOWN_KEY, counters["shown"] + 1)
    store.set_setting(STREAK_KEY, counters["streak"] + 1)  # 未互动前先记为忽略


def on_worse_notify(profile: str) -> bool:
    """异常提醒是否允许（只受总开关控制；危险永远忠言逆耳）。"""
    store = get_store()
    return bool(store.get_setting("notify_enabled", True))


def extra_line(profile: str, last_tip_index: int | None = None) -> tuple[str, int]:
    """extra 方案的附加语；返回 (文案, 本次使用的 tip 序号)。"""
    index = 0 if last_tip_index is None else (last_tip_index + 1) % len(TIPS)
    return TIPS[index], index
