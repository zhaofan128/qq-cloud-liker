#!/bin/bash
# NapCat 容器内一键安装（自包含，不依赖容器能访问 GitHub）
# 用法：bash <(curl -fsSL https://cdn.jsdelivr.net/gh/zhaofan128/qq-cloud-liker@main/deploy/setup.sh)
set -u

mkdir -p /app/napcat/config

# ---------- 1. OneBot HTTP 接口配置 ----------
if [ ! -f /app/napcat/config/onebot11.json ]; then
cat > /app/napcat/config/onebot11.json <<'JSONEOF'
{
  "network": {
    "httpServers": [
      {
        "name": "qqliker",
        "enable": true,
        "host": "127.0.0.1",
        "port": 3000,
        "enableCors": true,
        "enableWebsocket": false,
        "messagePostFormat": "array",
        "token": "",
        "debug": false
      }
    ],
    "httpClients": [],
    "websocketServers": [],
    "websocketClients": []
  },
  "musicSignUrl": "",
  "enableLocalFile2Url": false,
  "parseMultMsg": false
}
JSONEOF
echo "① 已写入接口配置，需要重启一次 NapCat 才会生效。"
echo "   请回应用详情点 Restart，等 Running 后重新执行本命令。"
exit 0
fi

# ---------- 2. 点赞脚本 ----------
cat > /app/dailylike.py <<'PYEOF'
"""云端名片赞：在 NapCat 容器里按点调用 OneBot send_like。"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

API = os.environ.get("ONEBOT_API", "http://127.0.0.1:3000").rstrip("/")
TIMES = int(os.environ.get("LIKE_TIMES", "10"))
AT = os.environ.get("LIKE_AT", "10:00")
GAP = float(os.environ.get("LIKE_GAP", "1.2"))
MAX_FRIENDS = int(os.environ.get("MAX_FRIENDS", "0"))
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_REPO = os.environ.get("GITHUB_REPO", "").strip()
TZ = timezone(timedelta(hours=8))
LOG_PATH = os.environ.get("LOG_PATH", "/app/like.log")


def log(msg: str) -> None:
    line = f"[{datetime.now(TZ):%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def api(action: str, payload: dict | None = None, timeout: int = 25):
    body = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        f"{API}/{action}", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def wait_online(limit: int = 900):
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            r = api("get_login_info", {}, timeout=5)
            if r.get("data") and r["data"].get("user_id"):
                return r["data"]
        except Exception:
            pass
        time.sleep(5)
    return None


def run_once() -> dict:
    info = wait_online()
    if not info:
        log("协议端未登录，跳过本轮")
        return {"ok": 0, "skipped": 0, "failed": 0, "note": "未登录"}

    log(f"已连接 {info.get('nickname')}({info.get('user_id')})")
    try:
        api("set_online_status", {"status": 7}, timeout=10)
        log("在线状态 -> 隐身")
    except Exception:
        pass

    try:
        fl = api("get_friend_list", {}, timeout=30)
    except Exception as exc:
        log(f"拿好友列表失败: {exc}")
        return {"ok": 0, "failed": 0, "skipped": 0, "note": "好友列表失败"}

    friends = fl.get("data") or []
    if not isinstance(friends, list) or not friends:
        log("好友列表为空")
        return {"ok": 0, "failed": 0, "skipped": 0, "note": "好友为空"}

    targets = [(str(f.get("user_id")), str(f.get("remark") or f.get("nickname") or ""))
               for f in friends]
    random.shuffle(targets)
    if MAX_FRIENDS > 0:
        targets = targets[:MAX_FRIENDS]

    log(f"共 {len(targets)} 位好友，每人 {TIMES} 个赞")

    ok = skip = fail = 0
    detail = []
    for i, (uin, name) in enumerate(targets, 1):
        state, msg = "fail", ""
        try:
            r = api("send_like", {"user_id": int(uin), "times": TIMES})
            rc = r.get("retcode")
            if r.get("status") == "ok" and (rc is None or int(rc) == 0):
                state, msg = "ok", f"+{TIMES}"
                ok += 1
            else:
                state = "skip"
                msg = f"跳过({r.get('status')}/{rc} {r.get('message') or ''})"
                skip += 1
        except Exception as exc:
            fail += 1
            msg = f"失败 {exc}"
        log(f"[{i}/{len(targets)}] {name}({uin}) {msg}")
        detail.append({"uin": uin, "name": name, "state": state, "msg": msg})
        if i < len(targets):
            time.sleep(GAP * (0.7 + random.random() * 0.6))

    log(f"本轮完成：成功 {ok} / 跳过 {skip} / 失败 {fail}")
    rec = {
        "name": "名片赞", "engine": "napcat-cloud", "status": "completed",
        "conclusion": "success" if fail == 0 else "partial",
        "created_at": datetime.now(TZ).isoformat(),
        "ok": ok, "skipped": skip, "failed": fail,
        "total": len(targets), "times": TIMES, "detail": detail,
    }
    save_record(rec)
    return rec


def save_record(rec: dict) -> None:
    path = os.environ.get("RUNS_PATH", "/app/runs.json")
    runs = []
    try:
        with open(path, encoding="utf-8") as f:
            runs = json.load(f)
        if not isinstance(runs, list):
            runs = []
    except Exception:
        runs = []
    runs.append(rec)
    runs = runs[-60:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=1)
    except Exception as exc:
        log(f"写本地记录失败: {exc}")
    if GH_TOKEN and GH_REPO:
        try:
            push_runs(runs)
        except Exception as exc:
            log(f"回传 GitHub 失败: {exc}")


def gh(path: str, method: str = "GET", payload: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GH_REPO}/{path}",
        data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": f"Bearer {GH_TOKEN}",
                 "User-Agent": "qqliker-cloud",
                 "Accept": "application/vnd.github+json"},
        method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def push_runs(runs: list) -> None:
    import base64
    content = base64.b64encode(
        json.dumps(runs, ensure_ascii=False, indent=1).encode()).decode()
    cur = gh("contents/data/runs.json")
    gh("contents/data/runs.json", "PUT", {
        "message": f"chore: 名片赞记录 {datetime.now(TZ):%m-%d %H:%M}",
        "content": content, "sha": cur["sha"]})
    log("执行记录已回传 GitHub")


def main() -> None:
    if "--once" in sys.argv:
        run_once()
        return
    hh, mm = (int(x) for x in AT.split(":"))
    log(f"常驻启动，每天 {AT} 执行（时区 UTC+8）")
    last_day = ""
    while True:
        now = datetime.now(TZ)
        today = f"{now:%Y-%m-%d}"
        if today != last_day and now.hour == hh and now.minute >= mm:
            last_day = today
            try:
                run_once()
            except Exception as exc:
                log(f"本轮异常: {exc}")
        time.sleep(20)


if __name__ == "__main__":
    main()
PYEOF

chmod +x /app/dailylike.py
pkill -f "python3 /app/dailylike.py" 2>/dev/null
sleep 1
nohup python3 /app/dailylike.py >> /app/like.log 2>&1 &
sleep 2

echo ""
if pgrep -f "python3 /app/dailylike.py" >/dev/null; then
    echo "daily liker started ✓"
    echo "每天 ${LIKE_AT:-10:00}（北京时间）给全部好友各点 ${LIKE_TIMES:-10} 个名片赞"
    echo ""
    echo "立刻试一次： python3 /app/dailylike.py --once"
    echo "看日志：     tail -f /app/like.log"
else
    echo "启动失败，看下日志： tail -20 /app/like.log"
fi
