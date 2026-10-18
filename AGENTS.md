# AGENTS.md — 挖兔硬盘精灵（WatuDiskSprite）开发接手指南

> **给任何 AI / 新开发者的第一份必读文件。**
> 本文件是**唯一权威的工程约定来源**。README.md 面向最终用户，本文件面向接手开发的人。
> 若README.md 与本文件冲突，**以本文件为准**。

---

## 0. 一句话定位

Windows 硬盘健康检测工具。PySide6 桌面应用，**单文件绿色版 exe**，全程离线、只读、不写注册表。
核心价值：SMART 全绿的盘也可能已经坏了（坏道在SMART 记录前就表现为「读得特别慢」），本软件用**盘面扫描**补上这个盲区。

---

## 1. ★★ 项目边界铁律（最高优先级，违反即严重失误）

###1.1 本项目只管这一个软件
- 本仓库 = **挖兔硬盘精灵软件本体**，唯一维护对象。
- **`ytb.com` 网站是另一个独立项目**（用户另有工作空间维护）。
  -❌ **禁止修改、完善、触碰任何网站文件**
  - ❌ 禁止在 website 目录、网站备份、站点压缩包里做任何增删改
  - ✅ 论坛/推广文案归网站侧，本仓库 `docs/` 不再堆宣发材料
  - 若用户在本会话里提到网站需求，**转交给他自己的网站空间**，不要动手

### 1.2 为什么这条这么重要（血泪教训）
历史上曾把「网站」和「软件」放在同一空间开发，导致 AI 上下文错乱、误判改动范围、用户为此不安。
**软件与网站必须物理隔离、职责隔离。**

### 1.3 其他项目（只读，勿动）
`D:\Projects\` 下还有 `jpeditor`（Rust+Tauri）、`YTDownloader-Pro`、`视频批量压缩器`（与本项目**共用同一套 PySide6**）。
这些项目**不在本仓库范围内**，不要跨项目改动。

---

## 2. ★★ 用户对改动方式的三条硬规矩

这三条是用户明确要求，任何 AI 必须遵守：

### 2.1 改前先备份，且必须验证备份有效
```
cp目标文件 备份路径
sha256sum 目标文件 备份文件     # 两者哈希必须一致，才算备份成功
```
- ⚠️ **曾经出过「备份与现文件一字不差」的糗事** —— 那是改完之后才复制的，等于没备份。
- ⚠️ **曾经把改完后的文件当作「原始备份」提交给用户**，说法不准确，是严重失信。
- 备份应放在项目内或工作区，**不要放`D:\Projects\DiskGuard\backup\`**（该目录已清理）。

### 2.2 先给改动清单，用户点头后再落代码
- **禁止先斩后奏**。
- 流程：只读调研 → 列出「改哪个文件 / 改什么内容 / 为什么」→ 等用户确认 → 才动代码。
- 用户常只点名单个问题，此时**只改那一条**，不要借机"顺手优化"其它地方。

### 2.3 最小化改动
- 能改 1 个文件就不动 2 个。
- 不碰无关文件、不做无关重构、不升级依赖、不格式化。
- 改动完成后**明确报告**：动了什么、没动什么、验证证据。

---

## 3. ★★ 发布流程铁律（最易违反）

>用户原话：「我没同意千万别发出去」「我自己也要用」

### 3.1 绝对禁止未经确认的发布动作
-❌ `git commit` / `git push`
- ❌ 创建 GitHub / Gitee Release
- ❌ 上传 exe / zip 资产
- ❌ 改远端仓库任何内容

### 3.2 唯一正确的发布顺序
```
本地改代码 → 回归全绿 → 本地构建 exe → 用户实测 →用户明确说"验收通过" → 才允许发布
```

### 3.3 授权范围
- 运营方向、开发方向、排期：**AI 可自主决定**。
- **唯独「发布 / 公开代码」节点必须停下等用户确认。**
- 用户已明确说过「可以发布 GitHub 和 Gitee」时，**该授权仅对当次版本有效**，不代表后续版本自动授权。

### 3.4 发布渠道
| 平台 | 地址 | 备注 |
| --- | --- | --- |
| GitHub（主） | `github.com/fan138/WatuDisk` | 源码 + Release 资产 |
| Gitee（国内镜像） | `gitee.com/fan188/WatuDisk` | 用户在网页端「强制同步」拉取源码 |

- **发布令牌**存于 `D:\Projects\DiskGuard\.workbuddy\publish_secrets.json`（gitignored，**绝不入库**）。
  脚本运行时读取，**绝不打印 / 回显 / 写进 shell 历史**。
- **本机网络限制**：`github.com:443` 被阻断，但 `api.github.com` / `codeload` / `objects.githubusercontent.com` 通。
  → **发布必须走 GitHub REST API**（建 blob→tree→commit→PATCH ref→Release→上传资产），不能用 `git push`。
- **代理坑**：走 API 前必须 `unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy` 后直连。
- **Gitee API** 走 `access_token` 查询参数，**不要用 `git push`**（非交互环境会静默挂起并返回退出码 0，误判成功）。
- Gitee Contents API 有速率限制，**逐文件写入、间隔 20–25 秒**。

---

## 4. 版本基线与项目状态（v1.2.2 收官版）

### 4.0 ★ 项目已收官（2026-10-18 用户拍板）

**v1.2.2 是收官之作：功能定型，不再增加新功能**，只持续修复问题、跟进 Windows 新版兼容性。

- 已从「下一版计划」中**移除**：邮件 / 微信提醒（违背「完全离线」核心卖点）、Intel VMD / RAID、SAS、Linux GUI 移植；
- 未纳入构想（smartctl 报告导入 / USB 桥接增强 / 趋势图 / i18n）已移入 README「项目状态」节与 GitHub Issues，**想法不丢，但不开工**；
- 复活条件（值得重开功能开发的情况）：star / 下载量明显上涨、外部需求变多、Windows 大版本兼容问题；
- **收官 ≠ 不管**：出现确认的 bug 仍以小版本（v1.2.3）响应，发布铁律不变。

### 4.1 版本指纹

| 版本 | 状态 | git 提交 | exe SHA-256 |
| --- | --- | --- | --- |
| v1.2.1 | 已发布（GitHub + Gitee） | `cd6b36e1d4d2103d01f60a7cf0e76b376ab0fd59` | `d8aab8fca070dc7e3b23c6bc154c592e5cf6bf73b673c73a0fc016e859ecd785` |
| v1.2.2 | 收官版，**已发布**（GitHub Release v1.2.2 + Gitee 待同步） | Release tag `3c94cd64ca2c`（发布锚点；main 后续仅有文档类修正提交，发布内容以此 tag 为准）。本地平行提交（API 发布造成的同内容不同 SHA，属预期现象，勿惊慌） | `3eaaf5953b4cad6893c0b865c02843792e7c1dce9c99fd639232120f3e1e10fc`（`deploy/WatuDiskSprite_v1.2.2.exe`，28,103,697 B；含「健康记录」标签合并 + 性能优化；历史构建归档于 `.workbuddy/backup_20261018_healthtab/`，优化前全量备份在 `backup_before_perf_20261018/`） |

### 4.2 v1.2.2 改了什么（2026-10-18 实现）

- **#20 寿命「假数据」双向校验**（核心）：`verdict.resolve_wear_used()` 成为判读 / metrics / 界面三处共用入口——NVMe 优先直读 percentage_used（255=未上报）；Wear=0 且通电 ≥10,000 小时判「未提供」。修掉金士顿 SA400「通电 4.3 万小时却显示剩余 100%」；
- **#14 固件版本**：`_DISK_PROPS` 加 FirmwareVersion，WMI 通道用 FirmwareRevision，详情页「基本信息」行展示；
- **#15 温度口径文案**：界面与报告说明「复合温度 = 盘内最高传感器」；
- **#10 启动提速**（实测驱动）：fsutil 改直调（`run_exe_text`，每卷省约 2 秒）+ WMI 兜底按需调用（省约 4 秒）。启动体检实测约 35 秒 → 优化后省约 8-10 秒；
- 文案收官：「?」弹窗「下一版计划」→「功能定型」声明；README 加「项目状态」节；
- **提醒记录 + 防打扰（2026-10-18 晚追加，用户反馈「有点热」气泡一飘而过）**：`tray.notify_custom` 统一收口——异常级（warn/danger）气泡弹出即写 `store.notify_log()`（有界 200 条；修复了该接口 v1.0 起只写内存不读回的持久化 bug），info 级不记；`notify_policy.should_notify_worse` 同类异常 4 小时冷却（danger 豁免、总开关优先、脏时间串放行）；主界面新增 `ReminderPanel` 折叠面板（复用 historyCard 样式对象名，零 CSS 改动），点异常气泡 `wake_up_and_show_reminders` 直达；开机体检的空间告急从 Information 改 Warning（本就是异常，否则不记录也不响应点击）；新增 `test_v122_reminder_log_qa`（19 例）；
- **健康记录合并（2026-10-18 深夜，用户拍板「以后的每个版本都并入 1.2.2」后追加）**：`HistoryPanel` / `ReminderPanel` 各占一张卡片 → 合并为 `HealthRecordPanel`（QStackedWidget + 两个 slim 子面板，`embedded=True` 时无自有头部、`_expanded` 恒 True、折叠开关失效）。默认标签=体检记录，`health_tab` / `health_expanded` 两个设置项持久化；`DiskCard._collapse_history_below` 收起链优先命中 `_health_panel`（旧 `_history_panel`/`_reminder_panel` 分支保留兜底，源码守卫仍守它们）；新增 `#healthTab` QSS（`:checked` 驱动激活态，无需 repolish）。**教训**：源码守卫比索引位置时，docstring 里的字样会干扰——要比就比完整代码模式（`getattr(node, "_health_panel"`）。
- 测试：新增 `test_v122_life_no_data_qa`（19 例）；`test_v12_wear_false_alarm_qa` 标签随「未提供（早期硬盘）」→「未提供」更新；`test_v12_score_explain_qa` 的「下一版计划」守卫改写为「功能定型」守卫。
- **性能优化（2026-10-18 深夜-19 日凌晨，用户批准「实测驱动、功能锁定」模式）**：cProfile 实测完整检测 39.9s 中 99.9% 在等 9 次 PowerShell 子进程 → ① `disk_info.get_disks_with_counters()` 一条命令同时取枚举+计数器（`_detect` 改走它；两个原公开函数保留，测试/QA 直接调用不受影响）；② `volume_check` 对 `Get-Partition` 稳定返回空的系统（实测本机管理员下也空）当日缓存失败结论（设置键 `partmap_std_failed_date`，次日自动重置重试），省每次约 7.5s 必然失败；③ WMI 通道下分区关联+卷空间合并为一次调用（`_MERGE_SEP` 分隔符三段 JSON，入口 `_collect_volume_maps`）。结果：检测 39.9→14.8s（-63%）、exe 端到端 35-45→约 19s、子进程 9→5 次、内存峰值不变（61.5→61.3MB）、真机对比合并 API 与旧 API 输出逐字段一致（仅温度允许 ±2°C 自然波动）。新增 `test_v122_perf_pipeline_qa`（13 例）；**修了 `test_v11_detect_e2e_offscreen` 的 mock 覆盖缺口**（合并查询走 `run_ps_text`，旧测试只 patch `run_ps_json`，导致真实 WMI 成功返回、「全失败」场景失效）。优化前全量备份在 `backup_before_perf_20261018/`（gitignored）。
- 构建环境更正（2026-10-18 踩坑）：打包必须用托管 venv 3.13（PyInstaller 6.22.2），详见 5.1 / 5.5。全量回归在系统 3.8.6 与 venv 3.13.14 下均 **481/481 全绿**，exe 自带 `--selftest` / `--smoke` exit=0。

### 4.3 改动前自检
```bash
cd D:/Projects/DiskGuard
git status --porcelain          # 应只看到 ?? 未跟踪项，不应有已跟踪文件的修改
git ls-files | wc -l                # 基线跟踪文件数 + 新增测试文件
```

---

## 5. ★★ 开发环境（实测，非推测）

### 5.1 两个环境，分工明确（2026-10-18 实测更正）

| 用途 | 解释器 | 关键组件 |
|---|---|---|
| 运行源码 / 自检 / 回归测试 | `C:\Program Files\python\python.exe` | Python 3.8.6 + PySide6 6.6.3.1 |
| **打包 exe（唯一可用）** | `C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe` | Python 3.13.14 + PySide6 6.11.2 + **PyInstaller 6.22.2** |

- ⚠️ **打包必须用 venv 那个**：已发布的 v1.2.1 成品内嵌 `python313.dll`；系统 Python 只带 PyInstaller 3.6，**解析不了 spec 里的 `hooksconfig`**（报 `TypeError: __init__() got an unexpected keyword argument 'hooksconfig'`）——2026-10-18 用错解释器构建失败过一次，别再踩。
- ⚠️ WorkBuddy 托管的**基础** 3.13（`versions\3.13.12`）确实是空壳（无 PySide6/PyInstaller），但同目录 `envs\default` venv 两样都有，**别把两者搞混**。
- 代码使用 `dict[str, int]` / `list[dict] | None` 等新式注解，但**每个文件都有 `from __future__ import annotations`**，故 3.8 与 3.13 都能跑。
  - ⚠️ 若新增文件用了新式注解，**必须在文件顶部加 `from __future__ import annotations`**，否则 3.8 下会 `TypeError`。

### 5.2 常用命令
```bash
PY="C:/Program Files/python/python.exe"

# 运行源码
"$PY" src/main.py

# 自检（改完必跑）
QT_QPA_PLATFORM=offscreen "$PY" src/main.py --selftest

# 语法全量编译检查
"$PY" -m compileall -q src/

# 跑全量回归（约 5 分钟）
cd test && QT_QPA_PLATFORM=offscreen "$PY" run_v12_regression.py
```

### 5.3 ★ 跑回归的前置条件
- **必须先关掉正在运行的 `WatuDiskSprite.exe`**。单实例探测用例会误报。
- 2026-10-18 修过回归编排器预检的两个 bug：① 查的进程名是改名前的 `DiskGuard.exe`，永远匹配不到真实进程（预检形同虚设）；② `text=True` 按 UTF-8 解码 tasklist 的 GBK 输出，会炸 reader thread 让整个回归挂掉（`UnicodeDecodeError` → `IndexError`）。现已改为按字节捕获 + GBK 解码。
- 遇到预检报错时，**不要打断用户使用**，改为自己手动逐个跑测试模块验证。

### 5.4 exe 自检超时
- exe 首次冷启动解压可能超过 120 秒，`timeout 120` 会**误报退出码 124**。
- **用 `timeout 300`**。

### 5.5 打包（必须用 venv 解释器，见 5.1）
```bash
PYBUILD="C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

cd src
# 先确认 3.13 + PySide6 6.11.2 组合下自检通过（约 10 秒）
QT_QPA_PLATFORM=offscreen "$PYBUILD" main.py --selftest
# 再打包（约 2-3 分钟）
"$PYBUILD" -m PyInstaller --clean --noconfirm --distpath dist --workpath build/pyinstaller build/diskguard.spec
```
- ⚠️ **UPX 工具当前缺失**：spec 的 `upx_paths` 指向 `build\tools\upx-4.2.4-win64`，该目录已在 2026-10-08 清理中移走。
  当前打包会跳过压缩（不影响 exe 可用性，只是体积略大）。若需 UPX，从官网下载并放回该路径，或修改 spec 的 `upx_paths`。
- 产物在 `src/dist/WatuDiskSprite.exe`。校验 SHA-256 后**以新文件名复制到 `deploy/`**（如 `WatuDiskSprite_v1.2.2.exe`），**严禁覆盖已发布成品**。
- `docs/` 之外的构建中间产物（`build/pyinstaller`、`src/dist`、`src/build/pyinstaller`）**可随时删除**，是纯可重建缓存。

---

## 6. 目录结构与模块职责

```
D:\Projects\DiskGuard\
├── src\
│   ├── main.py                入口：提权 / 单实例 / --selftest / --smoke
│   ├── core/                  核心逻辑（零第三方依赖，可独立单测）
│   ├── ui/                    PySide6 界面
│   ├── assets/                图标（.ico/.png）
│   ├── data/                  运行时数据
│   └── build/diskguard.spec   PyInstaller 配置
├── test/                30 个 test_*.py + run_v12_regression.py 编排器
├── deploy/                    ★ 已发布成品（不要动）
├── docs/screenshots/          README 引用的截图
├── images/                    README 引用的界面图
├── design/icon_rounded/       图标源文件（icon_02.png 为正式图标）
├── AGENTS.md                  ★ 本文件
└── README.md面向用户的产品说明
```

### 6.1 `core/`（20 个模块，纯逻辑 / 无 GUI 依赖）

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `disk_info.py` | 344 | 物理磁盘枚举（**双通道兜底**）+ 可靠性计数器（经 PowerShell） |
| `smart_parser.py` | 253 | SATA SMART 原始属性解析（厂商字典 21→78 条） |
| `nvme_health.py` | 224 | NVMe 健康日志直读（ctypes IOCTL，含国产主控固件） |
| `verdict.py` | 524 | **评分引擎 + 六档等级**（纯逻辑、无 IO，便于单测） |
| `metrics.py` | 336 | 指标阈值 → 0-3 警示等级与颜色 |
| `surface_scan.py` | 705 | ★ 盘面扫描（只读坏道检测 + 20×20=400 格分区） |
| `store.py` | 286 | 有界持久化（体检记录 200 条自动淘汰 / 忽略项 / 设置） |
| `report.py` | 534 | HTML 报告导出 |
| `tender.py` | 315 | 200+ 条温度提醒文案库 |
| `autostart.py` | 200 | 开机自启（启动文件夹 `.lnk`，**不写注册表**） |
| `event_scan.py` | 126 | 系统事件日志扫描（近 30 天）与归因 |
| `notify_policy.py` | 118 | 五种提醒方案 + 习惯降噪 |
| `volume_check.py` | 252 | 卷损坏位（Dirty Bit）检查 |
| `sysidle.py` | 97 | 系统空闲判断（定时体检只在空闲时跑） |
| `powershell_runner.py` | 87 | 统一 PowerShell 子进程封装 |
| `care_tips.py` | 76 | 护盘小贴士文案 |
| `shutdown_guard.py` | 56 | 关机 / 重启前只读复查 |
| `resource_path.py` | 33 | 资源路径统一解析（frozen / 源码双态） |

### 6.2 `ui/`（6 个模块）
| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `main_window.py` | 2209 | 主窗口（概览 / 逐盘卡片 / 体检记录多选删除 / 帮助弹窗 / 异步开机启动） |
| `surface_scan_dialog.py` | — | 盘面扫描窗口（**非模态**）、盘面地图自绘 |
| `tray.py` | — | 托盘常驻，图标随健康档位变色 |
| `toast.py` | — | 自绘气泡提醒（不受 Windows 勿扰模式影响） |
| `theme.py` | — | QSS 主题 |
| `shutdown_filter.py` | — | 关机事件过滤 |

---

## 7. ★★ 特殊注意事项（踩过的坑，务必先读）

### 7.1 ★★ 打包排除清单陷阱（最易复发）
`src/build/diskguard.spec` 有**两处**排除清单：
- `Analysis(excludes=[...])`
- `_EXCLUDE_BINARY_PATTERNS`（v1.5 瘦身，额外剔除二进制）

**给 `main_window.py` 新增任何 Qt 模块依赖前，必须先检查这两处。**

真实事故：`PySide6.QtSvg` / `Qt6Svg.dll` 被排除 → exe 启动即 `ModuleNotFoundError: PySide6.QtSvg`。
- ⚠️ **`--selftest` 测不出来**，因为它不 import `main_window`。
- 验证方法：查 `build/pyinstaller/diskguard/*.toc` 里是否有 `QtSvg.pyd` + `Qt6Svg.dll`。
- 已有回归守卫：`test_qa_svg_icon_dependency_is_packaged`（`test_v12_ui_report_qa.py`）。

### 7.2 ★★ Qt 模态对话框病根
`dialog.exec()` 是**模态**的，窗口一 `hide()` 就会阻塞父窗口。
→ 凡是「需要后台跑 + 父窗口继续可交互 + 联动显示进度」的场景，**一律不能 `exec()`**，必须改 `show()`。
盘面扫描的「隐藏后主窗口仍可操作、按钮实时显示进度」就是这个问题的解法。

### 7.3 ★★ 盘面扫描绝不能用 chkdsk
- 盘面扫描走**只读逐块物理读**（OVERLAPPED 异步 + 单块 5s 超时 + `CancelIoEx`）。
- **❌ 绝不可用 `chkdsk /r`** —— 它会写盘，破坏「只读」承诺。
- **中止的扫描绝不能报「未发现读失败」**（中止 ≠ 干净）。

### 7.4 ★★ 慢阈值必须用相对值
- 盘面地图慢块阈值 = **本次成功块耗时中位数 ×3 / ×10**。
- **无基准绝不标黄/橙**（绝对阈值在机械盘/SSD 上会大面积误报）。

### 7.5 ★★ 界面必须写明抽查密度
- 20×20 = 400 格热力图是**抽查**，不是整格都扫过，界面与报告**必须写明**。
- 慢阈值无基准不标色。这两条是**防误导铁律**。

### 7.6 ★★ 版本号有两处
```
src/main.py        APP_VERSION = "v1.2.1"
src/core/report.py APP_VERSION = "v1.2.1"
```
- **两处都要改**，相关测试有版本断言需同步。
- 报告标题取 `core.report.APP_VERSION`，**不能 import main**（会循环依赖）。

### 7.7 ★★ 界面不得出现自相矛盾措辞
- ❌ 不得出现「v1.2 开发中」这类与实际版本矛盾的字样。
- 底部按钮顺序固定：开始全盘检测 → 盘面扫描 → 导出报告 → 开机自动启动 → 开机静默体检 → GitHub → 只读提示 → `?`。

### 7.8 ✅ 已修复：SATA SSD「寿命剩余」误显示为 100%（Issue #20，v1.2.2 已修）

- **原现象**：金士顿 SA400S37120G（通电 43,393 小时 / 写入约 64 TB），
  官方 SSD Manager 与 CrystalDiskInfo 均显示**剩余寿命 54%**，本软件曾显示**寿命剩余 100%**。
- **根因链**：SA400 不在标准 SMART 属性里报告寿命 → Windows `Get-StorageReliabilityCounter`
  拿不到真实值时 **Wear 填回 0** → 旧版 `100-0=100%` → UI 显示「寿命剩余 100%」。
- **讽刺点**：v1.2.0 防过同一 API 的另一面坑（Wear=100 假「寿命耗尽」），但**没防假 0**。
- **修复**（v1.2.2，三层统一走 `verdict.resolve_wear_used()`）：
  Wear=0 且通电 ≥10,000 小时 → 判「未提供」；NVMe 优先直读 percentage_used（255=未上报）；
  界面 / 指标表 / 报告同步显示「未提供」。健康分口径不变（该盘确实健康）。
  守卫测试：`test_v122_life_no_data_qa.py`（16 例）。
- **★ 通用教训（写给未来的接手者）**：
  **`Get-StorageReliabilityCounter` 的 Wear 字段两端都不可信（0 与 100 都可能是「无数据」的默认值）。**
  凡是「默认值」语义的字段，都必须做**双向校验**（既防假耗尽，也防假全新），
  并交叉验证是否有硬件告警佐证（真快坏的盘必然伴随坏块增长）。

### 7.9 口径问题清单（已全部有解）
- **NVMe 温度**：显示复合温度，与 AIDA64 等差~20℃。**v1.2.2 已在界面与报告补充口径说明**（复合温度=盘内最高传感器），无 +20 偏移 bug。
- **CRC 接口错误提示过头**：**v1.2.0 已修**（`verdict.py` `_CRC_ALERT_THRESHOLD = 100`，与 metrics CAUTION 对齐，c7<100 只如实告知不劝换线）。
- GitHub Issue #12–#15 中：#12（枚举兜底）、#13（脏位）、#16（CRC）均已在 v1.2.0 代码中修复、仅 issue 未关；#14（固件）v1.2.2 已做；#15（温度口径）v1.2.2 已补文案。**关 issue 需要令牌补 Issues 写权限**（见第 3 节）。

---

## 8. ★ 测试纪律

### 8.1 新增测试文件末尾**必须**有
```python
if __name__ == "__main__":
    from _runner import run_module_tests
    sys.exit(run_module_tests(__name__))
```
- ⚠️ **漏了这行会被回归静默跳过，表现为「假绿灯」**。这个坑踩过。

### 8.2 判断回归是否真跑全
- **看总用例数有没有变大**，不能只看「全部通过」。
- `run_v12_regression.py` 已加自检：模块报告 0 用例会报警并计入失败。

### 8.3 ★ 测试要守价值，不守形式
> 真实教训：改了用户不要的行为，旧测试会变红 —— **这不一定是新 bug**。

案例：用户明确要求「全盘档免二次确认」，旧测试 `test_full_mode_requires_confirmation` 因此变红。
正确做法是**改写为 `test_full_mode_warns_duration_without_popup`** —— 守的是**用户价值（耗时必须告知）**，而非实现形式（弹不弹窗）。
删除二次确认时，**耗时告知必须留在界面文案里**（「可能要几个小时」「预计 xx」）。

### 8.4 GUI 测试
- 必须 `QT_QPA_PLATFORM=offscreen`。
- 新增 UI 测试可用 `_svg_icon()` + `QSvgRenderer` 渲染线性图标。

---

## 9. 临时文件与清理约定

- 清理出的构建产物、中间文件**移入项目内 `_trash_<日期>/` 暂存区**（可反悔），确认无用后再删。
  - ⚠️ 本机**回收站 API 全部被安全策略拦截**（`Add-Type`、Shell COM、程序集加载均失败），`Remove-Item` 不可恢复 → **一律用 `mv` 到暂存区**。
- 浏览器自动化每次运行会在**项目内**留下完整浏览器 profile（每份约 323 MB，含 `ProvenanceData` 168MB + `component_crx_cache` 155MB）。
  -⚠️ **每做一次浏览器验证就会堆一份，永不自动清**。用完应立即清理。
- 临时产物建议放项目内 `_trash_*`，**不要污染 D 盘根目录**。
- 清理前**必须校验 git 零误删**：
  ```bash
  git status --porcelain | grep -c "^ D"   # 必须为 0
  ```

---

## 10. 快速自检清单（提交前逐条确认）

```
□ git status 确认无意外改动
□ 改动的文件是否都必要（最小化改动）
□ 有新Qt 模块依赖？→ 检查 spec 两处排除清单 + toc 验证
□ 新增测试文件带 _runner 尾行？
□ 回归总用例数变大了？（不是只看"全绿"）
□ exe --selftest 通过（timeout 300）？
□ 界面文案无自相矛盾、无绝对阈值误报？
□ README/AGENTS 需同步更新？
□ 改动清单已告知用户？（未擅自发布）
```

---

## 11. 联系方式与协作
- 反馈渠道：GitHub Issues（`github.com/fan138/WatuDisk/issues`）；Gitee 镜像提 Issue 国内更顺。
- 语气口径：不防御、不硬杠、不贬低竞品；承认差距（如U盘桥接是 CDI 强项）。
- **渠道策略**：不再发 52pojie（用户 2026-10-07 决定），主渠道 = GitHub Release。

---

*最后更新：2026-10-08 · 对应版本 v1.2.1（基线提交 `cd6b36e`）*
