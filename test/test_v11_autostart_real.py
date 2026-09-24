# -*- coding: utf-8 -*-
"""v1.1 autostart 容错与真实启动文件夹演练（QA 自编）。

覆盖：
- 注入临时目录下的 enable 幂等（重复 enable 不报错、结果一致）；
- PowerShell 失败模拟（run_ps_text 返回 None / 返回非 LNK_OK 文本）-> enable 容错返回 False；
- 非法 / 不存在的 startup_dir -> enable 返回 False 不抛异常；
- 真实启动文件夹写入-查询-删除演练：创建 .lnk -> 验证存在与 IconLocation -> 立即删除，
  恢复演练前的原始状态，不留残留。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(TEST_DIR, "..", "src")))
sys.path.insert(0, TEST_DIR)

from core import autostart  # noqa: E402
from core.powershell_runner import run_ps_text  # noqa: E402


def _tmp_dir() -> str:
    return tempfile.mkdtemp(prefix="diskguard_qa_startup_")


def test_enable_is_idempotent():
    tmp = _tmp_dir()
    try:
        assert autostart.enable(tmp) is True
        first_mtime = os.path.getmtime(autostart.lnk_path(tmp))
        # 再次 enable：仍成功，.lnk 仍存在
        assert autostart.enable(tmp) is True
        assert autostart.is_enabled(tmp) is True
        assert os.path.isfile(autostart.lnk_path(tmp))
        del first_mtime  # 幂等性以存在性为准，mtime 不做强断言（COM 重写会更新）
        # disable 两次：都成功（第二次幂等）
        assert autostart.disable(tmp) is True
        assert autostart.disable(tmp) is True
        assert not os.path.exists(autostart.lnk_path(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_enable_tolerates_missing_startup_dir():
    """注入不存在的目录：PowerShell CreateShortcut 失败 -> 返回 False，不抛异常。"""
    tmp = _tmp_dir()
    missing = os.path.join(tmp, "no", "such", "dir")
    try:
        result = autostart.enable(missing)
        assert result is False, "不存在的 startup_dir 应返回 False"
        assert autostart.is_enabled(missing) is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_enable_tolerates_invalid_path_chars():
    """非法路径字符：返回 False，不抛异常。"""
    result = autostart.enable('X<>:"|?*illegal')
    assert result is False
    assert autostart.is_enabled('X<>:"|?*illegal') is False


def test_enable_tolerates_ps_failure(monkeypatch_enabled=True):
    """模拟 PowerShell 失败（run_ps_text 返回 None）：enable 容错返回 False。"""
    original = autostart.run_ps_text
    tmp = _tmp_dir()
    try:
        autostart.run_ps_text = lambda *a, **k: None
        assert autostart.enable(tmp) is False
        assert autostart.is_enabled(tmp) is False

        # 模拟 PowerShell 成功退出但未产出 LNK_OK（如脚本被拦截）
        autostart.run_ps_text = lambda *a, **k: "SOME_UNEXPECTED_OUTPUT"
        assert autostart.enable(tmp) is False
    finally:
        autostart.run_ps_text = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_enable_script_contains_expected_fields():
    """生成的 PowerShell 脚本应包含 TargetPath / IconLocation / LNK_OK 校验等关键字段。"""
    captured: dict = {}

    def fake_runner(script, timeout=20, **kwargs):
        captured["script"] = script
        return "LNK_OK"

    original = autostart.run_ps_text
    tmp = _tmp_dir()
    try:
        autostart.run_ps_text = fake_runner
        assert autostart.enable(tmp) is True
        script = captured["script"]
        assert "WScript.Shell" in script
        assert "TargetPath" in script
        assert "IconLocation" in script
        assert "WorkingDirectory" in script
        assert "LNK_OK" in script
        assert autostart.LNK_FILENAME in script
        # 默认图标应为 src/assets/diskguard.ico（开发态）
        assert "diskguard.ico,0" in script
    finally:
        autostart.run_ps_text = original
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# 真实启动文件夹演练（创建后立即删除，恢复原状态）
# ----------------------------------------------------------------------
def _read_lnk_fields(lnk_path: str) -> dict:
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$l = $ws.CreateShortcut('{lnk_path}'); "
        "Write-Output ($l.TargetPath); "
        "Write-Output ($l.IconLocation); "
        "Write-Output ($l.WorkingDirectory)"
    )
    text = run_ps_text(script, timeout=20)
    assert text, "无法读取 .lnk 字段"
    lines = [line.strip() for line in text.splitlines()]
    return {
        "target": lines[0] if len(lines) > 0 else "",
        "icon": lines[1] if len(lines) > 1 else "",
        "workdir": lines[2] if len(lines) > 2 else "",
    }


def test_real_startup_folder_drill():
    """真实启动文件夹：写入 -> 查询 -> 立即删除，验证 .lnk 与 IconLocation。"""
    real_dir = autostart.default_startup_dir()
    assert os.path.isdir(real_dir), f"真实启动文件夹不存在：{real_dir}"
    lnk = autostart.lnk_path()

    # 记录演练前状态，结束后恢复
    existed_before = os.path.isfile(lnk)

    try:
        # 1) 写入
        assert autostart.enable() is True, "真实启动文件夹 enable 失败"
        assert os.path.isfile(lnk), "DiskGuard.lnk 未出现在真实启动文件夹"

        # 2) 查询：字段校验
        fields = _read_lnk_fields(lnk)
        assert fields["target"], f"TargetPath 为空：{fields}"
        expected_icon = os.path.normpath(
            os.path.join(TEST_DIR, "..", "src", "assets", "diskguard.ico")
        )
        assert fields["icon"].lower().startswith(expected_icon.lower()), (
            f"IconLocation={fields['icon']} 应以 {expected_icon} 开头"
        )
        assert "diskguard" in fields["icon"].lower()

        # is_enabled 反映真实状态
        assert autostart.is_enabled() is True

        # 3) 立即删除
        assert autostart.disable() is True
        assert not os.path.exists(lnk), "演练后 DiskGuard.lnk 残留未删除"
        assert autostart.is_enabled() is False
    finally:
        # 恢复演练前状态：原本启用则重建，原本未启用确保已删除
        if existed_before:
            autostart.enable()
        elif os.path.isfile(lnk):
            autostart.disable()


def test_real_startup_dir_default_layout():
    """默认启动目录应位于 %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup。"""
    real_dir = autostart.default_startup_dir()
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        normalized = os.path.normcase(os.path.normpath(real_dir))
        expected = os.path.normcase(
            os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        )
        assert normalized == expected, f"{normalized} != {expected}"
    assert "Startup" in real_dir


if __name__ == "__main__":
    from _runner import run_module_tests

    sys.exit(run_module_tests(__name__))
