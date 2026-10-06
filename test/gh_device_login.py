# -*- coding: utf-8 -*-
"""GitHub 设备码登录：轮询 access_token 并写入本地 git 凭据。只在本机使用。"""
import json
import subprocess
import sys
import time

DEVICE_CODE = "bc6e735619415941f2840490013e8233439139e7"
CLIENT_ID = "178c6fc778ccc68e1d6a"
INTERVAL = 5
MAX_WAIT = 870  # 与 expires_in 同步

curl = "curl.exe"


def post(url: str, data: str) -> dict:
    for attempt in range(4):  # 网络抖动自动重试
        raw = subprocess.run(
            [curl, "-s", "--retry", "2", "--connect-timeout", "15", "-X", "POST", url,
             "-H", "Accept: application/json", "-d", data],
            capture_output=True, text=True, timeout=30,
        ).stdout
        try:
            parsed = json.loads(raw)
            if "error" not in parsed or parsed.get("error") not in ("authorization_pending", "slow_down"):
                if "access_token" in parsed:
                    return parsed
            return parsed
        except ValueError:
            pass  # 空响应/半截响应 -> 重试
        time.sleep(3)
    return {"error": ""}


def main() -> int:
    waited = 0
    token = None
    while waited < MAX_WAIT:
        resp = post(
            "https://github.com/login/oauth/access_token",
            f"client_id={CLIENT_ID}&device_code={DEVICE_CODE}"
            "&grant_type=urn:ietf:params:oauth:grant-type:device_code",
        )
        waited += INTERVAL
        if "access_token" in resp:
            token = resp["access_token"]
            break
        err = resp.get("error", "")
        if err == "authorization_pending":
            time.sleep(INTERVAL)
            continue
        if err == "slow_down":
            time.sleep(INTERVAL + 3)
            continue
        if err == "":
            time.sleep(INTERVAL)
            continue
        print(f"FAILED: {err or resp}")
        return 1

    if not token:
        print("FAILED: 超时未授权")
        return 1

    # 写入本地 git 凭据（仅保存在本机用户目录）
    cred_path = os.path.expanduser("~") + r"\.git-credentials"
    entry = f"https://fan138:{token}@github.com"
    existing = ""
    if os.path.isfile(cred_path):
        with open(cred_path, encoding="utf-8") as handle:
            existing = handle.read()
    if "github.com" not in existing:
        with open(cred_path, "a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(entry + "\n")
    print("TOKEN_OK 已写入本机凭据 ~/.git-credentials")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
