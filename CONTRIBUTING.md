# 贡献指南（挖兔硬盘精灵）

感谢你关注本项目！这是一个完全离线、只读检测的硬盘健康守护工具，欢迎共建。

## 提需求 / 报 Bug
- 功能建议、误报反馈、检测不全：请到 [Issues](https://github.com/fan138/WatuDisk/issues) 留言；
- 已规划的方向见 [#11 v1.2 路线图](https://github.com/fan138/WatuDisk/issues/11)。

## 开发约定（给想 PR 的同学）
- 语言：Python 3.13 + PySide6；检测核心 `src/core/` 保持零第三方依赖；
- 原则：**只读、离线、不收集任何数据**；任何会写盘到用户硬盘或联网上传的行为都需单独评估；
- 提交前请跑 `test/run_v12_regression.py` 回归（注意：运行前关闭正在运行的 WatuDiskSprite，避免单实例探测误报）；
- 版本号在 `src/main.py` 与 `src/core/report.py` 的 `APP_VERSION` 同步。

## 许可证
GPL-3.0（双许可）。衍生作品须同样以 GPL-3.0 开源并保留原作者署名。
