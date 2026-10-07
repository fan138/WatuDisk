# -*- coding: utf-8 -*-
"""临时诊断：为什么 _api_publish_v121.py 的 create-tree 返回 422 Invalid tree info。

分三步隔离：①仅 blobs ②仅 removed ③全部；同时检查 base tree 里
与要写入路径冲突的「目录 vs 文件」。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _api_publish_v121 as P  # noqa: E402

print(f"远端 base_tree 取自 HEAD")
ref = P.api("GET", f"{P.API}/git/ref/heads/main")
base_sha = ref["object"]["sha"]
base_commit = P.api("GET", f"{P.API}/git/commits/{base_sha}")
base_tree = base_commit["tree"]["sha"]

existing = P.api("GET", f"{P.API}/git/trees/{base_tree}?recursive=1")
nodes = existing.get("tree", [])
print(f"远端 tree 节点数: {len(nodes)}")
dirs = {n["path"] for n in nodes if n["type"] == "tree"}
print(f"其中目录节点 {len(dirs)} 个")

files: list[str] = [f for f in P.INCLUDE_FILES if os.path.isfile(f)]
for prefix in P.INCLUDE_ROOTS:
    if os.path.isdir(prefix.rstrip("/")):
        files.extend(P.collect_files(prefix.rstrip("/")))

seen: set[str] = set()
blobs: list[dict] = []
for path in files:
    if not os.path.isfile(path) or path in seen:
        continue
    seen.add(path)
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.strip():
        continue
    blob = P.api("POST", f"{P.API}/git/blobs",
                 {"content": base64.b64encode(data).decode(), "encoding": "base64"})
    blobs.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

print(f"本地待写文件: {len(blobs)} 个")
names = [b["path"] for b in blobs]
dups = {n for n in names if names.count(n) > 1}
print(f"重复路径: {dups or '无'}")

# 冲突：本地要写的路径，在远端是「目录」
conflict = [n for n in names if n in dirs]
print(f"本地文件 vs 远端目录冲突: {conflict or '无'}")

removed = [
    {"path": n["path"], "mode": "100644", "type": "blob", "sha": None}
    for n in nodes
    if n["type"] == "blob" and n["path"].startswith("docs/")
    and not n["path"].startswith("docs/screenshots/")
]
print(f"待删除条目: {len(removed)} 个 -> {[r['path'] for r in removed][:5]}")


def try_tree(payload: dict, label: str) -> None:
    try:
        res = P.api("POST", f"{P.API}/git/trees", payload)
        print(f"[{label}] OK -> tree {res['sha']}")
    except Exception as exc:
        print(f"[{label}] FAIL -> {str(exc)[:200]}")


try_tree({"base_tree": base_tree, "tree": blobs}, "仅 blobs")
try_tree({"base_tree": base_tree, "tree": removed}, "仅删除项")
try_tree({"base_tree": base_tree, "tree": blobs + removed}, "全部")
