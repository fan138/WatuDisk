# -*- coding: utf-8 -*-
"""powershell_runner 独立单元测试（含负面测试：超时保护、非法 JSON）。

另验证 Windows 下 subprocess.run 传入了 CREATE_NO_WINDOW 创建标志（用 mock 拦截）。
"""
from __future__ import annotations

import os
import sys
import time
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import powershell_runner  # noqa: E402


def test_create_no_window_constant():
    assert powershell_runner.CREATE_NO_WINDOW == 0x08000000


def test_run_ps_text_basic():
    text = powershell_runner.run_ps_text("Write-Output 'qa_ok'", timeout=20)
    assert text is not None
    assert "qa_ok" in text


def test_run_ps_text_utf8_chinese():
    text = powershell_runner.run_ps_text("Write-Output '中文输出测试'", timeout=20)
    assert text is not None
    assert "中文输出测试" in text, f"中文输出乱码或丢失: {text!r}"


def test_run_ps_text_failure_returns_none():
    """命令不存在 / 退出码非零 -> 返回 None 而非抛异常。"""
    result = powershell_runner.run_ps_text("this-cmd-does-not-exist-xyz", timeout=20)
    assert result is None


def test_run_ps_text_timeout_returns_none():
    """超时命令：保护生效、返回 None、不抛异常、耗时接近 timeout 而非等满命令时长。"""
    started = time.perf_counter()
    result = powershell_runner.run_ps_text("Start-Sleep -Seconds 60", timeout=2)
    elapsed = time.perf_counter() - started
    assert result is None, "超时应返回 None"
    assert elapsed < 15, f"超时应在秒级生效，实际耗时 {elapsed:.1f}s"


def test_run_ps_json_valid():
    result = powershell_runner.run_ps_json("$d = @{a = 1; b = 'x'}; Write-Output ($d | ConvertTo-Json)", timeout=20)
    assert isinstance(result, dict)
    assert result["a"] == 1
    assert result["b"] == "x"


def test_run_ps_json_array():
    result = powershell_runner.run_ps_json("Write-Output (@(1, 2, 3) | ConvertTo-Json)", timeout=20)
    assert result == [1, 2, 3]


def test_run_ps_json_invalid_output_returns_none():
    """输出不是合法 JSON -> None，不抛异常。"""
    result = powershell_runner.run_ps_json("Write-Output 'this is not json {{{'", timeout=20)
    assert result is None


def test_run_ps_json_empty_output_returns_none():
    result = powershell_runner.run_ps_json("Write-Output ''", timeout=20)
    assert result is None


def test_run_ps_json_timeout_returns_none():
    result = powershell_runner.run_ps_json("Start-Sleep -Seconds 60", timeout=2)
    assert result is None


def test_subprocess_gets_create_no_window_flag():
    """用 mock 拦截 subprocess.run，断言 Windows 下传入了 CREATE_NO_WINDOW 标志。"""
    fake_proc = mock.Mock()
    fake_proc.returncode = 0
    fake_proc.stdout = b"ok"
    fake_proc.stderr = b""
    with mock.patch.object(powershell_runner.subprocess, "run", return_value=fake_proc) as mocked:
        text = powershell_runner.run_ps_text("Write-Output ok")
    assert text == "ok"
    kwargs = mocked.call_args.kwargs
    if os.name == "nt":
        assert kwargs.get("creationflags") == 0x08000000, "Windows 下必须传 CREATE_NO_WINDOW 防黑框"
    assert kwargs.get("capture_output") is True


def test_subprocess_oserror_returns_none():
    """subprocess 抛 OSError（如找不到 powershell）应返回 None。"""
    with mock.patch.object(powershell_runner.subprocess, "run", side_effect=OSError("boom")):
        assert powershell_runner.run_ps_text("anything") is None


def test_subprocess_timeout_raises_is_caught():
    with mock.patch.object(
        powershell_runner.subprocess, "run", side_effect=__import__("subprocess").TimeoutExpired(cmd="x", timeout=1)
    ):
        assert powershell_runner.run_ps_text("anything") is None


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
