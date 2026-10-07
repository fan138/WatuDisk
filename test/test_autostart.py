# -*- coding: utf-8 -*-
"""autostart.py 开机启动独立单元测试（QA 自编）。

使用临时目录注入 startup_dir 参数，绝不写用户真实启动文件夹；
测完清理，不留残留。enable() 走真实 PowerShell WScript.Shell COM。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core import autostart  # noqa: E402
from core.powershell_runner import run_ps_text  # noqa: E402


def _make_tmp_startup_dir() -> str:
    return tempfile.mkdtemp(prefix="diskguard_test_startup_")


def test_lnk_path_uses_injected_dir():
    injected = os.path.join("Z:", os.sep, "whatever")
    assert autostart.lnk_path(injected) == os.path.join(injected, autostart.LNK_FILENAME)
    # 默认路径应落在 APPDATA 下的 Startup 目录
    default_path = autostart.lnk_path()
    assert "Startup" in default_path and default_path.endswith(autostart.LNK_FILENAME)


def test_enable_disable_roundtrip():
    tmp = _make_tmp_startup_dir()
    try:
        assert not autostart.is_enabled(tmp), "临时目录初始不应存在 .lnk"
        assert autostart.enable(tmp) is True, "enable 应成功创建 .lnk"
        assert autostart.is_enabled(tmp) is True
        assert os.path.isfile(autostart.lnk_path(tmp))
        assert autostart.disable(tmp) is True
        assert autostart.is_enabled(tmp) is False
        assert not os.path.exists(autostart.lnk_path(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_disable_idempotent_when_absent():
    tmp = _make_tmp_startup_dir()
    try:
        assert autostart.disable(tmp) is True, ".lnk 不存在时 disable 应视为成功（幂等）"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_lnk_target_points_to_current_program():
    """创建的快捷方式 TargetPath 应指向当前解释器（frozen 时为 exe）。"""
    tmp = _make_tmp_startup_dir()
    try:
        assert autostart.enable(tmp) is True
        lnk = autostart.lnk_path(tmp)
        script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$l = $ws.CreateShortcut('{lnk}'); "
            "Write-Output $l.TargetPath"
        )
        target = run_ps_text(script, timeout=20)
        assert target, "应能读回快捷方式 TargetPath"
        target = target.strip().strip('"')
        expected_exe = sys.executable
        if not getattr(sys, "frozen", False):
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if os.path.isfile(pythonw):
                expected_exe = pythonw
        assert target.lower() == expected_exe.lower(), f"TargetPath={target} 期望 {expected_exe}"
    finally:
        autostart.disable(tmp)
        shutil.rmtree(tmp, ignore_errors=True)


def test_is_enabled_default_dir_readonly_check():
    """is_enabled() 只读检查：不应在默认目录创建任何文件。"""
    before = os.path.isfile(autostart.lnk_path())
    result = autostart.is_enabled()
    assert isinstance(result, bool)
    assert result == before, "is_enabled 不应改变开关状态"


def test_apply_preference_enables_when_true():
    """偏好为 True 时确保 .lnk 存在（含 --boot 迁移 + 旧品牌名迁移）。"""
    tmp = _make_tmp_startup_dir()
    try:
        assert autostart.apply_preference(True, tmp) is True
        assert autostart.is_enabled(tmp) is True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_apply_preference_disables_when_false():
    """偏好为 False 时确保 .lnk 不存在——用户关闭后不再被偷偷改回。

    这正是 AppInn 反馈的核心痛点：旧逻辑每次启动无条件 enable，
    取消勾选后下次又自动勾上。apply_preference(False) 必须保持关闭。
    """
    tmp = _make_tmp_startup_dir()
    try:
        autostart.enable(tmp)
        assert autostart.is_enabled(tmp) is True
        assert autostart.apply_preference(False, tmp) is False
        assert autostart.is_enabled(tmp) is False
        # 再调用一次仍为 False（幂等，不会偷偷重建）
        assert autostart.apply_preference(False, tmp) is False
        assert autostart.is_enabled(tmp) is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_apply_preference_retries_enable_on_transient_failure():
    """首次 enable 偶发失败时，apply_preference(True) 应重试一次并成功建出 .lnk。

    对应首次打开软件时「界面勾选了但任务管理器启动项里却没有」的根因之一：
    WScript.Shell COM 在程序初始化阶段偶发失败，重试一次即可规避。
    """
    tmp = _make_tmp_startup_dir()
    try:
        calls = {"n": 0}
        real_enable = autostart.enable

        def flaky_enable(startup_dir=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return False  # 模拟首次 COM 偶发失败
            return real_enable(startup_dir)

        autostart.enable = flaky_enable
        try:
            assert autostart.apply_preference(True, tmp) is True
            assert autostart.is_enabled(tmp) is True
            assert calls["n"] == 2, "应恰好重试一次 enable"
        finally:
            autostart.enable = real_enable
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
