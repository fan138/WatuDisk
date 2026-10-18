# -*- coding: utf-8 -*-
"""统一的 PowerShell 子进程调用封装。

特性：
- CREATE_NO_WINDOW 防止黑框闪烁；
- 统一超时控制；
- JSON 输出解析；
- 任何失败（超时 / 非零退出码 / 解析失败）均返回 None，由调用方优雅降级。
"""
from __future__ import annotations

import json
import os
import subprocess

# 防止弹出黑色控制台窗口（仅 Windows 有效）
CREATE_NO_WINDOW = 0x08000000

DEFAULT_TIMEOUT = 30

_POWERSHELL_PREFIX = (
    "$ErrorActionPreference = 'SilentlyContinue'; "
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
)


def _decode_output(data: bytes) -> str:
    """按优先级尝试多种编码解码子进程输出。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def run_ps_text(command: str, timeout: int = DEFAULT_TIMEOUT, check_code: bool = True) -> str | None:
    """执行 PowerShell 命令，返回原始文本输出。

    Args:
        command: PowerShell 命令字符串。
        timeout: 超时秒数。
        check_code: 是否将非零退出码视为失败（fsutil 等工具
            退出码语义不标准，可传 False 以拿回输出再自行解析）。

    Returns:
        输出文本；任何失败返回 None。
    """
    full_command = _POWERSHELL_PREFIX + command
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-NoLogo",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        full_command,
    ]
    kwargs: dict = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run(cmd, **kwargs)  # noqa: S603 - 固定的可信系统程序
    except (subprocess.TimeoutExpired, OSError):
        return None
    if check_code and proc.returncode != 0:
        return None
    return _decode_output(proc.stdout)


def run_ps_json(command: str, timeout: int = DEFAULT_TIMEOUT) -> object | None:
    """执行输出为 JSON 的 PowerShell 命令并解析。

    Returns:
        解析后的对象（dict / list 等）；失败或空输出返回 None。
    """
    text = run_ps_text(command, timeout=timeout)
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_exe_text(argv: list[str], timeout: int = DEFAULT_TIMEOUT, check_code: bool = False) -> str | None:
    """直接执行系统 exe（不套 PowerShell 进程），返回文本输出。

    v1.2.2（#10 启动提速）：fsutil 等稳定系统工具原先走 run_ps_text，每次调用
    都要白付一次 PowerShell 冷启动（实测约 2 秒/次）。直调后降到几十毫秒，
    脏位查询从「每卷约 2.2 秒」降到几乎无感。

    Args:
        argv: 可执行文件 + 参数列表（如 ["fsutil", "dirty", "query", "C:"]）。
        timeout: 超时秒数。
        check_code: 是否将非零退出码视为失败（fsutil 退出码语义不标准，传 False）。

    Returns:
        输出文本；任何失败返回 None。
    """
    kwargs: dict = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run(argv, **kwargs)  # noqa: S603 - 固定的可信系统程序
    except (subprocess.TimeoutExpired, OSError):
        return None
    if check_code and proc.returncode != 0:
        return None
    return _decode_output(proc.stdout)
