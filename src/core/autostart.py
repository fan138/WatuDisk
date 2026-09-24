# -*- coding: utf-8 -*-
"""开机自启动（绿色方式：启动文件夹快捷方式，不写注册表）。

实现方式：在 shell:startup（%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup）
目录下创建 WatuDiskSprite.lnk 快捷方式，指向当前可执行文件：
- 打包态：直接指向 WatuDiskSprite.exe；
- 开发态：pythonw.exe + main.py（pythonw 避免启动时带出控制台窗口）。

PowerShell 调用统一走 powershell_runner（防黑框、超时、失败返回 None）；
所有公开函数失败容错返回 False，绝不抛异常。
"""
from __future__ import annotations

import os
import sys

from core.powershell_runner import run_ps_text

LNK_FILENAME = "WatuDiskSprite.lnk"
LEGACY_LNK_FILENAME = "DiskGuard.lnk"  # DiskGuard 时代的旧快捷方式，定稿迁移用

_TIMEOUT_SECONDS = 20


def legacy_lnk_path(startup_dir: str | None = None) -> str:
    """旧品牌快捷方式完整路径（定稿迁移用）。"""
    return os.path.join(startup_dir or default_startup_dir(), LEGACY_LNK_FILENAME)


def migrate_legacy_lnk(startup_dir: str | None = None) -> bool:
    """v1.0 定稿迁移：旧 DiskGuard.lnk 换成新 WatuDiskSprite.lnk。

    旧快捷方式指向的 exe/参数已过时；存在即重建新快捷方式（带 --boot
    静默参数）并删除旧文件。幂等，无旧文件时直接返回 True。
    """
    old = legacy_lnk_path(startup_dir)
    if not os.path.isfile(old):
        return True
    ok = enable(startup_dir)
    try:
        if ok:
            os.remove(old)
    except OSError:
        pass
    return ok


def default_startup_dir() -> str:
    """当前用户的启动文件夹路径（APPDATA 下的 Startup 目录）。"""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def lnk_path(startup_dir: str | None = None) -> str:
    """快捷方式完整路径；startup_dir 参数用于测试注入临时目录。"""
    return os.path.join(startup_dir or default_startup_dir(), LNK_FILENAME)


# ----------------------------------------------------------------------
# 快捷方式目标（程序 / 参数 / 工作目录）
# ----------------------------------------------------------------------
def _target() -> tuple[str, str, str]:
    """返回 (目标程序, 参数, 工作目录)。

    参数带 --boot：开机启动时进入「静默体检」模式（不弹窗口，
    延迟至系统空闲后体检一次，只更新托盘与体检记录）。手动双击
    exe 不带参数，仍弹主窗口。
    """
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return exe, "--boot", os.path.dirname(exe)
    # 开发态：优先 pythonw.exe（无控制台）
    python_exe = os.path.abspath(sys.executable)
    pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    if os.path.isfile(pythonw):
        python_exe = pythonw
    main_py = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main.py")
    )
    return python_exe, f'"{main_py}" --boot', os.path.dirname(main_py)


def _icon_location() -> str:
    """快捷方式图标：优先打包内的 ico，回退到目标程序自身图标。"""
    try:
        from core.resource_path import resource_path

        ico = resource_path("diskguard.ico")
        if ico:
            return ico
    except ImportError:
        pass
    target, _args, _workdir = _target()
    return target


def _ps_quote(text: str) -> str:
    """PowerShell 单引号字面量转义（内部单引号翻倍）。"""
    return "'" + str(text).replace("'", "''") + "'"


# ----------------------------------------------------------------------
# 开关接口
# ----------------------------------------------------------------------
def is_enabled(startup_dir: str | None = None) -> bool:
    """判断开机启动是否已启用（.lnk 是否存在）。"""
    return os.path.isfile(lnk_path(startup_dir))


def lnk_arguments(startup_dir: str | None = None) -> str:
    """读取快捷方式的启动参数；读取失败返回空串。"""
    lnk = lnk_path(startup_dir)
    if not os.path.isfile(lnk):
        return ""
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$lnk = $ws.CreateShortcut({_ps_quote(lnk)}); "
        "Write-Output $lnk.Arguments"
    )
    text = run_ps_text(script, timeout=_TIMEOUT_SECONDS)
    return str(text or "").strip()


def ensure_boot_argument(startup_dir: str | None = None) -> bool:
    """确保快捷方式带 --boot 静默参数（v1.5.1 兼容迁移）。

    旧版本创建的 .lnk 不带参数，开机时会弹出主窗口；检测到缺失就
    重写一次（幂等）。已带参数或未启用则不动。
    """
    if not is_enabled(startup_dir):
        return True  # 未启用无需迁移
    if "--boot" in lnk_arguments(startup_dir):
        return True
    return enable(startup_dir)


def enable(startup_dir: str | None = None) -> bool:
    """创建启动文件夹快捷方式；成功返回 True，任何失败返回 False。"""
    target, args, workdir = _target()
    lnk = lnk_path(startup_dir)
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$lnk = $ws.CreateShortcut({_ps_quote(lnk)}); "
        f"$lnk.TargetPath = {_ps_quote(target)}; "
        f"$lnk.Arguments = {_ps_quote(args)}; "
        f"$lnk.WorkingDirectory = {_ps_quote(workdir)}; "
        f"$lnk.IconLocation = {_ps_quote(_icon_location() + ',0')}; "
        f"$lnk.Description = {_ps_quote('挖兔硬盘精灵：开机自动运行（绿色版，不写注册表）')}; "
        "$lnk.Save(); "
        f"if (Test-Path -LiteralPath {_ps_quote(lnk)}) {{ Write-Output 'LNK_OK' }} "
        "else { Write-Output 'LNK_FAIL' }"
    )
    text = run_ps_text(script, timeout=_TIMEOUT_SECONDS)
    return bool(text) and "LNK_OK" in text


def disable(startup_dir: str | None = None) -> bool:
    """删除启动快捷方式；本就不存在视为成功（幂等），删除失败返回 False。"""
    path = lnk_path(startup_dir)
    if not os.path.isfile(path):
        return True
    try:
        os.remove(path)
        return True
    except OSError:
        return False
