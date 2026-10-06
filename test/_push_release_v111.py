# -*- coding: utf-8 -*-
"""后台任务：重试 git push 直连；成功后自动创建 Release v1.1.1 并上传 exe。"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

LOG = r"D:\Projects\DiskGuard\test\_push_release_status.log"
GIT = r"D:\Tools\GitSetup\mingit\cmd\git.exe"
CWD = r"D:\Projects\DiskGuard"
EXE = os.path.join(CWD, "deploy", "WatuDiskSprite.exe")
TAG = "v1.1.1"
REPO = "fan138/WatuDisk"

NOTES = """## 挖兔硬盘精灵 v1.1.1（2026-10-01）

### 新增 / 改进
- **指标「忽略」功能升级**：点击忽略后该项不再影响评分，评分回归剩余项的真实水平；颜色警示仍保留，作为提醒继续显示（忽略与恢复即时生效，建议文字同步更新）
- **检测数据显示更全**：温度、通电时间/次数、累计读写量、备用空间等指标增加多级数据兜底（系统计数器 → NVMe 健康日志 → SMART 原始值），尽量少显示「—」
- **NVMe 危险警告具名拆解**：固件自报危险警告时按规范分解为备用空间不足 / 过热 / 介质退化 / 只读保护 / 掉电保护缓存失败，不再只给一句笼统提示
- **体检记录增强**：本地保留最近 200 次记录，界面展示最近 30 次并支持滚动；修复历史记录文字重叠问题
- **界面细节**：开机启动勾选与托盘菜单保持同步；移除窗口内重复的标题行；机械盘专属字段无数据时整行隐藏
- **v1.2 预告角标**：右上角淡灰「?」可查看下一版本功能预告（表面扫描 / 阈值提醒 / USB 识别增强），欢迎提建议

### 校验
- SHA-256: `E1DBB7DC33A35C2321165DDCA7553AEF6127835314079B01DBE4929EDA67EFD0`
- 回归测试 255/255 通过（含 selftest / smoke）
"""


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def clean_env() -> dict:
    env = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        env.pop(key, None)
    return env


def git(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, *args], cwd=CWD, env=clean_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def get_token() -> str:
    remote = git(["remote", "get-url", "origin"]).stdout.strip()
    # https://user:token@github.com/... → 先截 @ 前段，再取最后一个冒号后段
    before_at = remote.split("@")[0]
    return before_at.split(":")[-1].strip() if "@" in remote else ""


def api_request(url: str, token: str, data: bytes | None = None,
                headers: dict | None = None, method: str = "GET"):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "watu-release-script")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    return urllib.request.urlopen(req, timeout=60)


def main() -> int:
    log("=== push & release 任务启动（v1.1.1） ===")

    # ---- 1) 重试推送（最多 12 次，间隔 60s） ----
    pushed = False
    for attempt in range(1, 13):
        proc = git(["push", "origin", "main"])
        if proc.returncode == 0:
            log(f"push 成功（第 {attempt} 次尝试）")
            pushed = True
            break
        log(f"push 第 {attempt} 次失败: {(proc.stderr or '').strip()[-120:]}")
        time.sleep(60)
    if not pushed:
        log("12 次推送全部失败，任务结束（提交仍在本地，稍后可手动 push）")
        return 1

    # ---- 2) 创建 Release（已存在则跳过） ----
    token = get_token()
    if not token:
        log("未取得 token，跳过 Release 步骤")
        return 0
    try:
        api_request(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", token)
        log(f"Release {TAG} 已存在，跳过创建")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            log(f"查询 Release 失败: HTTP {exc.code}")
            return 1
        body = json.dumps({
            "tag_name": TAG, "target_commitish": "main",
            "name": f"挖兔硬盘精灵 {TAG}",
            "body": NOTES, "draft": False, "prerelease": False,
        }).encode("utf-8")
        try:
            api_request(f"https://api.github.com/repos/{REPO}/releases", token,
                        data=body, headers={"Content-Type": "application/json"},
                        method="POST")
            log(f"Release {TAG} 创建成功")
        except urllib.error.HTTPError as exc2:
            log(f"创建 Release 失败: HTTP {exc2.code} {exc2.read()[:200]}")
            return 1

    # ---- 3) 上传 exe 资产（已存在则先删后传） ----
    release = json.loads(api_request(
        f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", token
    ).read().decode("utf-8"))
    upload_base = release["upload_url"].split("{")[0]
    release_id = release["id"]
    existing = json.loads(api_request(
        f"https://api.github.com/repos/{REPO}/releases/{release_id}/assets", token
    ).read().decode("utf-8"))
    for asset in existing:
        if asset.get("name") == "WatuDiskSprite.exe":
            api_request(
                f"https://api.github.com/repos/{REPO}/releases/assets/{asset['id']}",
                token, method="DELETE")
            log("已删除旧资产 WatuDiskSprite.exe")

    with open(EXE, "rb") as handle:
        payload = handle.read()
    try:
        api_request(
            f"{upload_base}?name=WatuDiskSprite.exe", token, data=payload,
            headers={"Content-Type": "application/octet-stream"}, method="POST")
        log(f"资产上传成功（{len(payload):,} 字节）")
    except urllib.error.HTTPError as exc:
        log(f"资产上传失败: HTTP {exc.code}")
        return 1

    log(f"=== 全部完成：Release {TAG} 就绪 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
