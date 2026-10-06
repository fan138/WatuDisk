# -*- coding: utf-8 -*-
"""v1.2.0 发布：走 GitHub API 推 commit（github.com 主站被网络阻断，api通）。

为什么不用 git push：git 走 github.com:443 被卡（curl api.github.com 却通），
而 GitHub REST API 完全可以完成同样的事——创建 blob / tree / commit / 更新 ref。

用法： python _api_publish_v120.py <commit_message_file>
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = "fan138/WatuDisk"
BRANCH = "main"
TOKEN = os.environ["GH_TOKEN"]
API = f"https://api.github.com/repos/{REPO}"

# 只有源码 / 测试 / 文档 / 截图入库；docs/ 私密素材、构建产物、exe 一律不推
INCLUDE_ROOTS = ("src/", "test/", "images/", "docs/screenshots/")
INCLUDE_FILES = ("README.md", "CHANGELOG.md", "LICENSE", ".gitignore")
EXCLUDE_SUFFIX = (".pyc",)
EXCLUDE_PARTS = ("__pycache__", "/build/pyinstaller/", "/dist/", ".log", ".exe", ".zip")


def api(method: str, url: str, payload=None, retries: int = 3):
    """调用 GitHub API，失败自动重试（网络偶发抖动）。"""
    last = None
    for attempt in range(1, retries + 1):
        try:
            data = json.dumps(payload).encode() if payload is not None else None
            req = urllib.request.Request(
                url, data=data, method=method,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "watu-disk-publisher",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (502, 503, 504) and attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # 网络层抖动
            last = exc
            if attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(f"网络失败: {exc}") from exc
    raise RuntimeError(f"重试耗尽: {last}")


def collect_files(root: str) -> list[str]:
    """按白名单收集要入库的文件（相对路径，用 / 分隔）。"""
    picked: list[str] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "dist", "pyinstaller", "bin")]
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            posix = f"{root.replace(os.sep, '/')}/{rel}"
            if posix.endswith(EXCLUDE_SUFFIX) or any(p in posix for p in EXCLUDE_PARTS):
                continue
            picked.append(posix)
    return sorted(picked)


def build_payload(msg_file: str) -> dict:
    with open(msg_file, encoding="utf-8") as fh:
        message = fh.read().strip()

    # 1) 拿当前 ref 与基线 commit
    ref = api("GET", f"{API}/git/ref/heads/{BRANCH}")
    base_sha = ref["object"]["sha"]
    base_commit = api("GET", f"{API}/git/commits/{base_sha}")
    base_tree = base_commit["tree"]["sha"]

    files: list[str] = list(INCLUDE_FILES)
    for prefix in INCLUDE_ROOTS:
        files.extend(collect_files(prefix.rstrip("/")))

    seen: set[str] = set()
    blobs: list[dict] = []
    total_bytes = 0
    for path in files:
        if not os.path.isfile(path) or path in seen:
            continue
        seen.add(path)
        with open(path, "rb") as fh:
            data = fh.read()
        # 极小的占位文件跳过，避免无意义提交
        if not data.strip():
            continue
        total_bytes += len(data)
        blob = api("POST", f"{API}/git/blobs",
                   {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        blobs.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob  {path}  ({len(data)} B)")

    print(f"\n共{len(blobs)} 个文件，{total_bytes/1024:.0f} KB")

    # 2) 建 tree（基于当前 ref 的 tree，删除已不存在的路径）
    existing = api("GET", f"{API}/git/trees/{base_tree}?recursive=1")
    removed = [
        {"path": node["path"], "mode": "100644", "type": "blob", "sha": None}
        for node in existing.get("tree", [])
        if node["type"] == "blob"
        and any(p in node["path"] for p in ("docs/",))
        and not node["path"].startswith("docs/screenshots/")
    ]
    tree = api("POST", f"{API}/git/trees",
               {"base_tree": base_tree, "tree": blobs + removed})
    print(f"tree sha: {tree['sha']}（清理私密docs 文件 {len(removed)} 个）")

    # 3) 建 commit
    commit = api("POST", f"{API}/git/commits",
                 {"message": message, "tree": tree["sha"], "parents": [base_sha]})
    print(f"commit sha: {commit['sha']}")

    # 4) 更新 ref
    updated = api("PATCH", f"{API}/git/refs/heads/{BRANCH}",
                  {"sha": commit["sha"], "force": False})
    print(f"分支已更新 -> {updated['object']['sha']}")
    return {"commit": commit["sha"], "files": len(blobs), "removed": len(removed)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _api_publish_v120.py <commit_message_file>")
        raise SystemExit(2)
    result = build_payload(sys.argv[1])
    print(f"\n完成：{result['files']} 个文件已提交，commit {result['commit'][:8]}")
