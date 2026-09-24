# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：挖兔硬盘精灵 单文件正式版。

特性：
- 单文件 exe（onefile）、无控制台（windowed）、启动自动请求管理员权限（uac-admin）；
- 应用图标 assets/diskguard.ico（多尺寸 256~16）；
- assets/diskguard_base.png 随包分发（dest 'assets'，运行时经 resource_path 解析）；
- 排除不需要的标准库模块，减小体积。

打包命令（在仓库根目录执行）：
    python -m PyInstaller --clean --noconfirm --distpath dist --workpath build/pyinstaller build/diskguard.spec
"""

import os

# spec 相对路径的基准是 spec 所在目录（src/build），资源在其上级 src/assets
_ASSETS_DIR = os.path.normpath(os.path.join(SPECPATH, "..", "assets"))
_ICON_PATH = os.path.join(_ASSETS_DIR, "diskguard.ico")
_BASE_PNG_PATH = os.path.join(_ASSETS_DIR, "diskguard_base.png")

block_cipher = None

a = Analysis(
    ['../main.py'],
    pathex=[],
    binaries=[],
    datas=[(_BASE_PNG_PATH, 'assets'), (_ICON_PATH, 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc_data',
        'curses',
        'asyncio',
        'multiprocessing',
        'sqlite3',
        'distutils',
        'setuptools',
        'xmlrpc',
        'pyexpat',
        # v1.5 瘦身：本软件用不到的 Qt 模块（界面只用 Widgets/Gui/Core/Network）
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtUiTools',
        'PySide6.QtTest',
        'PySide6.QtDesigner',
        'PySide6.QtBluetooth',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.Qt3DCore',
        'PySide6.QtOpenGL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---- v1.5 瘦身：剔除与界面无关的大体积二进制 ----
# opengl32sw.dll（19.7MB 软件 OpenGL 回退）、d3dcompiler（ANGLE 专用）——
# 本软件是纯 Widgets/光栅渲染，不使用 OpenGL/D3D；
# Quick/Qml/Designer/Pdf/Charts 相关即使被依赖链带入也一并剔除。
_EXCLUDE_BINARY_PATTERNS = (
    'opengl32sw', 'd3dcompiler', 'Qt6Svg', 'Qt6Qml', 'Qt6Quick', 'Qt6Designer',
    'Qt6Pdf', 'Qt6Charts', 'Qt63D', 'Qt6Test', 'qtpyvcp',
)
a.binaries = [
    entry for entry in a.binaries
    if not any(pattern.lower() in entry[0].lower() for pattern in _EXCLUDE_BINARY_PATTERNS)
]
a.datas = [
    entry for entry in a.datas
    if 'translations' not in entry[0].lower()
]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WatuDiskSprite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_paths=[os.path.join(SPECPATH, '..', '..', 'build', 'tools', 'upx-4.2.4-win64')],
    upx_exclude=[
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'python313.dll',
        'Qt6Core.dll',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=_ICON_PATH,
)
