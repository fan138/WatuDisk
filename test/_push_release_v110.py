# -*- coding: utf-8 -*-
"""后台任务：重试 git push 直连；成功后自动创建 Release v1.1.0 并上传 exe。"""
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
TAG = "v1.1.0"
REPO = "fan138/WatuDisk"

NOTES = """## 挖兔硬盘精灵 v1.1.0（2026-10-01）

### 新增 / 改进
- **SMART 属性字典大扩充**：可识别属性 21 → 78 项（对照 ATA 规范与 CrystalDiskInfo / smartmontools 社区通行约定），更多属性直接显示中文名，不再满屏「未知属性 0xXX」
- **U 盘等无 SMART 设备如实标注「不支持」**：U 盘硬件层普遍不提供 SMART（任何工具都读不到健康度），此前显示满分有误导，现在如实展示
- **USB 设备提示更对症**：读不到健康数据时明确说明是设备/硬盘盒桥接限制，不再误提示为权限问题
- **判读文案打磨**：多项告警同时出现时更容易分清报警来源

### 校验
- SHA-256: `8DE97850A062F2AE8D76F66429D72858DEB8424C4ACBD813C44BB908FC0BFB7A`
- 回归测试 233/233 通过（含 selftest / smoke）
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
    if "PATH" in env and "Path" in env:
        del env["PATH"]
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
    log("=== push & release 任务启动 ===")

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
