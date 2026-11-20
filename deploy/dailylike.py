"""云端名片赞：在 NapCat 容器里按点调用 OneBot send_like。

不依赖 GitHub Actions，也不依赖任何电脑。容器一启动就常驻，
每天到点给全部好友各点 LIKE_TIMES 个名片赞。
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
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

LOG_PATH = "/app/like.log"


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
        f"{API}/{action}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def wait_online(limit: int = 900) -> dict | None:
    """等 QQ 登录成功（首次需要扫码）。"""
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

    targets = [
        (
            str(f.get("user_id")),
            str(f.get("remark") or f.get("nickname") or ""),
        )
        for f in friends
    ]
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
                msg = f"跳过({r.get('status')}/{rc} {r.get('message') or r.get('wording') or ''})"
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
        "name": "名片赞",
        "engine": "napcat-cloud",
        "status": "completed",
        "conclusion": "success" if fail == 0 else "partial",
        "created_at": datetime.now(TZ).isoformat(),
        "ok": ok,
        "skipped": skip,
        "failed": fail,
        "total": len(targets),
        "times": TIMES,
        "detail": detail,
    }
    save_record(rec)
    return rec


def save_record(rec: dict) -> None:
    path = "/app/runs.json"
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
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "User-Agent": "qqliker-cloud",
            "Accept": "application/vnd.github+json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")


def push_runs(runs: list) -> None:
    import base64

    content = base64.b64encode(
        json.dumps(runs, ensure_ascii=False, indent=1).encode()
    ).decode()
    cur = gh("contents/data/runs.json")
    gh(
        "contents/data/runs.json",
        "PUT",
        {
            "message": f"chore: 名片赞记录 {datetime.now(TZ):%m-%d %H:%M}",
            "content": content,
            "sha": cur["sha"],
        },
    )
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
