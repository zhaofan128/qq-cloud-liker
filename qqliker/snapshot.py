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


def fetch_friend_feeds(client: QzoneClient, num: int = 20) -> list[dict[str, Any]]:
    """好友动态。接口对参数敏感，拿不到就返回空列表，不影响其他数据。"""
    params = {
        "uin": client.uin,
        "scope": 0,
        "view": 1,
        "daylist": "",
        "uinlist": "",
        "gid": "",
        "flag": 1,
        "filter": 1,
        "applist": "",
        "refresh": 0,
        "style": 1,
        "fupdate": 1,
        "pagenum": 1,
        "num": num,
        "g_tk": client.gtk,
        "callback": "_Callback",
        "format": "jsonp",
    }
    try:
        resp = client.s.get(
            FEEDS_API, params=params, timeout=client.timeout, cookies=client.cookies
        )
        data = loads_js(resp.text)
    except Exception as exc:
        log.warning("好友动态拉取失败: %s", exc)
        return []

    main = ((data or {}).get("data") or {}).get("main") or {}
    raw = main.get("feeds") or []
    out: list[dict[str, Any]] = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        body = f.get("content") or f.get("html") or ""
        if isinstance(body, str):
            import re

            body = re.sub(r"<[^>]+>", "", body).strip()
        try:
            ts = int(f.get("abstime") or f.get("time") or 0)
        except (TypeError, ValueError):
            ts = 0
        out.append(
            {
                "nick": str(f.get("nickname") or f.get("name") or ""),
                "content": str(body)[:120],
                "time": ts,
                "uin": str(f.get("uin") or ""),
            }
        )
    return out


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

    snap["feeds"] = fetch_friend_feeds(client)
    try:
        snap["likes"] = fetch_like_list(client, my_feeds)
    except Exception as exc:
        snap["errors"].append(f"点赞列表失败: {exc}")
    return snap


def write_snapshot(snap: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 保留前端写入的抽屉配置（好友开关等），避免被定时同步覆盖
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old.get("config"), dict):
                snap["config"] = old["config"]
        except Exception:
            pass
    if "config" not in snap:
        snap["config"] = {"times": 10, "enabled": [f["uin"] for f in snap["friends"]]}
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("快照已写入 %s（好友 %d，动态 %d，赞 %d）", path, len(snap["friends"]), len(snap["feeds"]), len(snap["likes"]))
