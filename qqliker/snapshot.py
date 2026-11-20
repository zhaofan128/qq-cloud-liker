"""采集 App 需要的数据：好友列表、好友动态、谁赞了我。

输出一份 snapshot.json，前端 PWA 直接读，不需要任何后端。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .client import QzoneClient, QzoneError, loads_js

log = logging.getLogger("qqliker.snapshot")

FRIENDS_API = "https://h5.qzone.qq.com/proxy/domain/r.qzone.qq.com/cgi-bin/tfriend/friend_mngfrd_get.cgi"
FEEDS_API = "https://h5.qzone.qq.com/proxy/domain/ic2.qzone.qq.com/cgi-bin/feeds/feeds3_html_more"
LIKE_LIST_API = "https://h5.qzone.qq.com/proxy/domain/w.qzone.qq.com/cgi-bin/likes/get_like_list_app"


def fetch_friends(client: QzoneClient) -> list[dict[str, str]]:
    resp = client.s.get(
        FRIENDS_API,
        params={"uin": client.uin, "fupdate": 1, "scene": 21, "g_tk": client.gtk},
        timeout=client.timeout,
        cookies=client.cookies,
    )
    data = loads_js(resp.text)
    items = ((data or {}).get("data") or {}).get("items") or []
    out = []
    for it in items:
        uin = str(it.get("uin") or "").strip()
        if uin.isdigit():
            out.append({"uin": uin, "name": str(it.get("name") or it.get("nickname") or uin)})
    return out


def fetch_friend_feeds(
    client: QzoneClient,
    friends: list[dict[str, Any]] | None = None,
    per: int = 2,
    days: int = 3,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """好友动态：逐个好友取最新几条说说。

    之前用的 ``feeds3_html_more`` 常常返回空（data:[undefined]），
    所以这里改成走好友说说列表，稳定且顺带拿到 tid、方便点赞。
    """
    cutoff = time.time() - days * 86400
    out: list[dict[str, Any]] = []
    for item in (friends or [])[:limit]:
        fuin = str(item.get("uin") if isinstance(item, dict) else item)
        if not fuin.isdigit():
            continue
        try:
            feeds = client.list_feeds(num=per, uin=fuin)
        except Exception:
            continue
        name = str(item.get("name") or "") if isinstance(item, dict) else ""
        for f in feeds:
            if int(f.get("created_time") or 0) < cutoff:
                continue
            out.append(
                {
                    "nick": f.get("nick") or name,
                    "content": f.get("content", ""),
                    "time": int(f.get("created_time") or 0),
                    "uin": fuin,
                    "tid": f.get("tid", ""),
                }
            )
        time.sleep(0.12)
    out.sort(key=lambda i: i["time"], reverse=True)
    return out[:limit]


def fetch_like_list(client: QzoneClient, feeds: list[dict[str, Any]], limit: int = 6) -> list[dict]:
    """谁赞了我的说说：逐条查最近动态的点赞列表，汇总去重。"""
    seen: set[str] = set()
    out: list[dict] = []
    for feed in feeds[:limit]:
        if not feed.get("curkey"):
            continue
        try:
            resp = client.s.get(
                LIKE_LIST_API,
                params={
                    "uin": client.uin,
                    "unikey": feed["unikey"],
                    "curkey": feed["curkey"],
                    "fupdate": 1,
                    "g_tk": client.gtk,
                    "format": "json",
                },
                timeout=client.timeout,
                cookies=client.cookies,
            )
            data = loads_js(resp.text)
        except Exception:
            continue
        items = ((data or {}).get("data") or {}).get("like_list") or []
        for it in items:
            uin = str(it.get("uin") or "")
            if not uin or uin in seen:
                continue
            seen.add(uin)
            out.append(
                {
                    "uin": uin,
                    "name": str(it.get("name") or it.get("nickname") or uin),
                    "time": it.get("time") or 0,
                    "feed": str(feed.get("content") or "")[:40],
                }
            )
    return out


def build_snapshot(client: QzoneClient, friends: list[dict] | None = None) -> dict:
    snap: dict[str, Any] = {
        "updated_at": int(time.time()),
        "account": {"uin": client.uin, "name": ""},
        "friends": [],
        "feeds": [],
        "likes": [],
        "errors": [],
    }
    try:
        snap["account"]["name"] = client.check()
    except QzoneError as exc:
        snap["errors"].append(f"账号校验失败: {exc}")

    if friends is None:
        try:
            friends = fetch_friends(client)
        except Exception as exc:
            snap["errors"].append(f"好友列表失败: {exc}")
            friends = []
    snap["friends"] = friends

    try:
        my_feeds = client.list_feeds(num=10)
    except Exception as exc:
        snap["errors"].append(f"我的动态失败: {exc}")
        my_feeds = []

    snap["feeds"] = fetch_friend_feeds(client, friends)
    try:
        snap["likes"] = fetch_like_list(client, my_feeds)
    except Exception as exc:
        snap["errors"].append(f"点赞列表失败: {exc}")
    return snap


def write_snapshot(snap: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    # 配置以 config/control.json 为准（App 控制面板写入），其次沿用旧快照
    cfg = dict(snap.get("config") or {})
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old.get("config"), dict):
                cfg = {**old["config"], **cfg}
        except Exception:
            pass
    try:
        from .config import load_control

        ctrl = load_control(Path("config") / "control.json")
        if ctrl:
            cfg.update({k: v for k, v in ctrl.items() if v not in (None, "", [])})
    except Exception:
        pass

    cfg.setdefault("times", 10)
    cfg.setdefault("schedule", "10:00")
    cfg.setdefault("enabled", [f["uin"] for f in snap["friends"]])
    snap["config"] = cfg

    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("快照已写入 %s（好友 %d，动态 %d，赞 %d）", path, len(snap["friends"]), len(snap["feeds"]), len(snap["likes"]))
