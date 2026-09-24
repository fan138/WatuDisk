# 挖兔硬盘精灵（WatuDiskSprite）

面向 Windows 个人用户的硬盘健康检测软件：AI 时代大量读写容易让 SSD 在不知不觉中受损，
一旦崩溃往往猝不及防。WatuDiskSprite 的定位是「发现于未然」——提前预警。

- **绿色版**：单文件 exe，不写注册表、不产生垃圾文件（唯一写盘场景：用户主动导出 HTML 报告）
- **全程离线**：代码中无任何网络相关导入
- **只读检测**：绝不写入硬盘任何数据，不做物理坏道扫描
- **智能判读**：SMART 全属性 + 事件日志扫描 + 卷损坏位检查 + 综合评分（0-100）预警
- **免费无限制**

## 模块结构

```
src/
├── main.py                  # 入口：管理员提权检查 / 单实例保护 / --selftest / --smoke
├── core/
│   ├── powershell_runner.py # PowerShell 子进程统一封装（防黑框、超时、JSON 解析）
│   ├── disk_info.py         # Get-PhysicalDisk + Get-StorageReliabilityCounter（含专业指标）
│   ├── smart_parser.py      # SATA SMART 原始 362 字节属性解析（NVMe 跳过）
│   ├── event_scan.py        # 最近 30 天 System 日志磁盘相关错误/警告扫描
│   ├── volume_check.py      # fsutil dirty query 逐卷检查损坏位
│   ├── verdict.py           # 综合评分引擎 + 六档健康等级（纯逻辑、无 IO，可单测）
│   ├── resource_path.py     # 资源路径解析（开发态 src/assets / 打包态 _MEIPASS/assets）
│   ├── autostart.py         # 开机启动（绿色方式：启动文件夹 .lnk，不写注册表）
│   └── report.py            # HTML 报告构建与导出（内联 CSS，单文件，含专业指标）
├── ui/
│   ├── theme.py             # QSS 样式与配色常量（浅色 SaaS 风格 + 六档健康色）
│   ├── tray.py              # 系统托盘：程序化图标变色 / 2h 后台检测 / 单实例
│   └── main_window.py       # 主窗口 + 7 步体检动效清单 + QThread 后台检测
├── assets/                  # diskguard.ico（多尺寸图标）/ diskguard_base.png
└── build/
    └── diskguard.spec       # PyInstaller 打包配置（onefile/windowed/uac-admin/icon）
```

## v1.1 新增

- **漂亮图标**：exe 图标与窗口图标使用 assets/diskguard.ico，打包时资源经
  `core/resource_path.py` 统一解析（兼容开发态与 onefile 解压目录）
- **系统托盘常驻**（ui/tray.py）：QPainter 程序化绘制图标（圆角方底 + 白色简笔硬盘，
  危险档加白色感叹号），随健康状态在六档颜色间切换；单击唤起主窗口；
  关闭主窗口 = 最小化到托盘（首次气泡提示），退出仅从托盘菜单；
  后台 QTimer 每 2 小时静默检测一次，等级变差时气泡提醒一次（不重复轰炸）
- **六档健康等级**（core/verdict.py）：优秀(#1B7E3C) / 良好(#5FA83B) / 注意(#D99A0B) /
  警告(#DD6B1D) / 危险(#C93A3A) / 紧急(#8A1E1E)，未检测为灰；托盘与卡片徽章按六档配色，
  原三档结论语义与 force_danger / force_warning 钳制规则不变
- **开机启动（绿色方式）**（core/autostart.py）：在用户启动文件夹创建 WatuDiskSprite.lnk
  （PowerShell WScript.Shell COM），不写注册表；首次运行默认开启，
  主界面复选框与托盘菜单均可随时开关、两处状态即时同步
- **360 式动态体检**（main_window.py）：固定 7 步清单（枚举设备 → 健康状态 → SMART →
  温度寿命 → 事件日志 → 卷损坏位 → 评分建议），每步 待办灰点 → 旋转 spinner →
  绿色✓+结果摘要（失败橙色!+原因但继续）；进度条同步平滑推进，完成后清单淡出，
  显示「检测完成 · 用时 X 秒」
- **专业指标扩展**：Get-StorageReliabilityCounter 透传 TemperatureMin/Max、
  PowerCycleCount 等字段；SATA 盘补充 05/C5/C6/C7/09/0C 原始值；
  详情面板新增两列「专业指标」网格（通电时间「14,200 小时 · 约 1.6 年」、
  通电次数、加载/卸载循环、主轴启停、剩余寿命、温度极值、错误计数、坏扇区计数），
  取不到显示「—」，数值千分位，并同步进入 HTML 报告
- **单实例保护**：QLocalServer 命名管道，二次启动唤起已有实例后自动退出

## 运行

```powershell
# 正常运行（会自动请求管理员权限）
python src/main.py

# 核心逻辑自检（无需 GUI 与管理员权限，退出码 0 表示全部通过）
python src/main.py --selftest

# GUI 冒烟测试（窗口显示 2 秒后自动退出）
python src/main.py --smoke
```

## 打包

```powershell
python -m PyInstaller --clean --noconfirm --distpath dist --workpath build/pyinstaller src/build/diskguard.spec
```

产物：`dist/WatuDiskSprite.exe`（单文件绿色版，双击运行自动请求管理员权限；
用户拒绝 UAC 时进入「基础模式」，界面会明确提示数据受限）。

## 技术要点

- 除 PySide6 外零第三方依赖；系统数据一律通过 PowerShell（Get-PhysicalDisk /
  Get-StorageReliabilityCounter / Get-WinEvent）与 ctypes / fsutil 获取
- 所有 PowerShell 调用均容错：某一步失败只影响单项，界面降级显示「无法读取」而不崩溃
- SSD 磨损语义：StorageReliabilityCounter 的 Wear 为已消耗百分比，剩余寿命 = 100 - Wear
- 评分规则：健康 ≥ 80 / 警告 50-79 / 危险 < 50；C6>0 重扣、C5>0 中扣、
  重映射扇区随数量加扣、SSD 剩余寿命 <10% 重扣、温度 >70°C 扣分、
  30 天内磁盘错误事件按量扣分、损坏位置位重扣；理由全部为大白话
- 托盘 / 开机启动 / 单实例均为绿色实现：.lnk 放启动文件夹、QLocalServer 系统命名管道，
  不写注册表、不留临时文件；--smoke 模式下三者全部跳过，保证自动化干净退出
