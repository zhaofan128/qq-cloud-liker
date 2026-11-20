"""QQ 空间网页接口客户端。

设计要点
--------
1. 所有接口地址集中在 ``QzoneClient.ENDPOINTS``，QQ 改版时只改这一处即可。
2. 全程只复用浏览器 Cookie 发 HTTPS 请求，不登录 QQ 客户端、不走协议端，
   所以不会产生新的登录会话，也不会改变好友看到的在线状态。
3. 每个请求之间默认排队 1~2 秒，避免高频请求带来的账号风险。
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Iterable

import requests

log = logging.getLogger("qqliker.client")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# QQ 客户端标识，名片赞接口需要
QUA = "V1_AND_SQ_8.9.63_4338_YYB_D"


class QzoneError(RuntimeError):
    """接口返回异常 / 解析失败。"""


def parse_cookies(cookie: str) -> dict[str, str]:
    """把浏览器里复制出来的 Cookie 头解析成字典。"""
    out: dict[str, str] = {}
    for seg in cookie.replace("\n", ";").replace("\r", ";").split(";"):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, v = seg.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def calc_gtk(skey: str) -> int:
    """QZone 使用的 g_tk 算法：djb2 变体，取低 31 位。"""
    h = 5381
    for ch in skey:
        h += (h << 5) + ord(ch)
    return h & 0x7FFFFFFF


_CALLBACK_RE = re.compile(r"^[\w$.]+\((.*)\)\s*;?\s*$", re.S)
_HTML_CALLBACK_RE = re.compile(r"callback\(\s*(\{.*\})\s*\)", re.S)


def loads_js(text: str) -> Any:
    """解析 QQ 的 JSONP / JS 字面量响应。

    兼容三种形态：
    1. ``_Callback({...});``
    2. ``<html>...frameElement.callback({...});</script></html>``（点赞接口）
    3. 裸 JSON
    """
    text = (text or "").strip()
    if not text:
        raise QzoneError("空响应")
    if "<html" in text.lower() or "frameElement" in text:
        m = _HTML_CALLBACK_RE.search(text)
        if m:
            text = m.group(1).strip()
    m = _CALLBACK_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:  # 键不带引号时用 json5 兜底
        import json5  # type: ignore

        return json5.loads(text)
    except Exception:
        pass
    # 最后兜底：把裸键加上引号再试一次
    fixed = re.sub(r"([{,]\s*)([A-Za-z_][\w]*)(\s*:)", r'\1"\2"\3', text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as exc:
        raise QzoneError(f"无法解析响应: {text[:200]}") from exc


class _DryResponse:
    """dry-run 模式下的假响应，用于在不联网的情况下验证流程。"""

    def __init__(self, payload: Any, text: str | None = None) -> None:
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)
        self.status_code = 200

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class QzoneClient:
    ENDPOINTS = {
        # 自己的资料，用于校验 Cookie 是否有效
        "profile": "https://h5.qzone.qq.com/proxy/domain/base.qzone.qq.com/cgi-bin/user/cgi_userinfo_get_all",
        # 名片赞（截图里"赞了你 10 次"那个）：appid=7030 就是名片应用
        "like_card": "https://user.qzone.qq.com/proxy/domain/w.qzone.qq.com/cgi-bin/likes/internal_dolike_app",
        # 好友的空间主页，用来看"今天还能不能赞"（g_likeable_today）
        "profile_page": "https://user.qzone.qq.com/{fuin}",
        # 好友动态列表
        "list_feeds": "https://h5.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6",
        # 给单条动态点赞
        "like_feed": "https://h5.qzone.qq.com/proxy/domain/w.qzone.qq.com/cgi-bin/likes/internal_dolike_app",
    }

    def __init__(
        self,
        uin: str,
        cookie: str,
        *,
        timeout: int = 20,
        dry_run: bool = False,
        session: Any | None = None,
    ) -> None:
        self.uin = str(uin).strip()
        self.cookie = (cookie or "").strip()
        self.cookies = parse_cookies(self.cookie)
        skey = self.cookies.get("p_skey") or self.cookies.get("skey") or ""
        if not dry_run and not skey:
            raise QzoneError("Cookie 里没有 skey / p_skey，请重新从 user.qzone.qq.com 复制完整 Cookie")
        self.gtk = calc_gtk(skey)
        self.timeout = timeout
        self.dry_run = dry_run
        self.s = session if session is not None else requests.Session()
        try:
            self.s.headers.update(
                {
                    "User-Agent": UA,
                    "Referer": f"https://user.qzone.qq.com/{self.uin}",
                    "Origin": "https://user.qzone.qq.com",
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
            )
        except Exception:  # 测试用的 fake session 可能不支持
            pass

    # ------------------------------------------------------------------ 底层
    def _dry_payload(self, name: str) -> Any:
        if name == "profile":
            return {"code": 0, "data": {"nickname": "dry-run", "uin": int(self.uin or 0)}}
        if name == "like_card":
            return {"code": 0, "subcode": 0, "message": "succ"}
        if name == "like_feed":
            return {"code": 0, "data": {"ret": 0, "msg": "succ"}}
        return {"code": 0}

    def _call(
        self,
        name: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        method: str = "GET",
        url: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if self.dry_run:
            if name == "list_feeds":
                return _DryResponse(None, text=_dry_feed_jsonp())
            if name == "profile_page":
                return _DryResponse(
                    None, text='g_likeable_today=+"1", "like_number":+""'
                )
            return _DryResponse(self._dry_payload(name))
        target = url or self.ENDPOINTS[name]
        try:
            if method == "POST":
                resp = self.s.post(
                    target,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                    cookies=self.cookies,
                )
            else:
                resp = self.s.get(
                    target,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                    cookies=self.cookies,
                )
        except requests.RequestException as exc:
            raise QzoneError(f"{name} 请求失败: {exc}") from exc
        if resp.status_code >= 400:
            raise QzoneError(f"{name} HTTP {resp.status_code}")
        return resp

    # ------------------------------------------------------------------ 功能
    def check(self) -> str:
        """校验 Cookie 是否还有效，返回昵称。"""
        resp = self._call(
            "profile",
            params={"uin": self.uin, "vuin": self.uin, "g_tk": self.gtk, "format": "json"},
        )
        text = resp.text or ""
        if "登录" in text and "nickname" not in text:
            raise QzoneError("Cookie 已失效，需要重新获取")
        data = loads_js(text)
        if isinstance(data, dict) and data.get("code") not in (0, None):
            raise QzoneError(f"校验失败: {data}")
        nickname = ""
        if isinstance(data, dict):
            nickname = (
                (data.get("data") or {}).get("nickname")
                or (data.get("data") or {}).get("name")
                or data.get("nickname")
                or ""
            )
        return nickname or self.uin

    CARD_APPID = 7030  # 名片应用 appid，动态是 311

    def card_likeable_today(self, fuin: str) -> int | None:
        """查某个好友的名片今天还能不能赞。

        返回 1 = 今天还没赞过（可以赞），0 = 今天已经赞过，None = 没查到。
        判断依据是好友空间主页内联的 ``g_likeable_today`` 变量。
        """
        fuin = str(fuin).strip()
        try:
            resp = self._call(
                "profile_page",
                url=self.ENDPOINTS["profile_page"].format(fuin=fuin),
                headers={"Referer": f"https://user.qzone.qq.com/{self.uin}"},
            )
        except QzoneError:
            return None
        m = re.search(r"g_likeable_today\s*=\s*\+?\s*[\"']?(\d)", resp.text or "")
        if not m:
            return None
        return int(m.group(1))

    def like_card(self, fuin: str, times: int = 10, interval: float = 1.5) -> int:
        """给某个好友的名片点赞，最多 ``times`` 次，返回实际成功次数。

        走的是空间主页那个"赞"按钮背后的真实接口：
        ``likes/internal_dolike_app``，appid=7030，unikey/curkey 都是
        ``http://user.qzone.qq.com/{好友QQ}``。成功返回 ``message: "succ"``；
        旧的 ``friend_ship_manager.cgi`` 早已废弃，虽然也回 code=0，
        但其实什么也不做（这就是之前"显示成功却没点上"的原因）。
        """
        fuin = str(fuin).strip()
        key = f"http://user.qzone.qq.com/{fuin}"
        data = {
            "appid": self.CARD_APPID,
            "face": 0,
            "fupdate": 1,
            "from": 1,
            "query_count": 200,
            "opuin": self.uin,
            "unikey": key,
            "curkey": key,
            "dontadd": 0,
            "op": 1,
            "format": "json",
            "qzreferrer": f"https://user.qzone.qq.com/{fuin}",
        }
        headers = {"Referer": f"https://user.qzone.qq.com/{fuin}"}
        done = 0
        for i in range(max(0, times)):
            try:
                resp = self._call(
                    "like_card",
                    params={"g_tk": self.gtk},
                    data=data,
                    method="POST",
                    headers=headers,
                )
                payload = loads_js(resp.text)
            except QzoneError as exc:
                log.warning("好友 %s 第 %d 次点赞异常: %s", fuin, i + 1, exc)
                break
            if not isinstance(payload, dict):
                break
            if payload.get("message") == "succ" or payload.get("ret") == 0:
                done += 1
            else:
                # 今日上限 / 非好友 / 需要验证，均直接跳过
                log.info(
                    "好友 %s 第 %d 次点赞停止: code=%s %s",
                    fuin,
                    i + 1,
                    payload.get("code"),
                    payload.get("message", ""),
                )
                break
            if i < times - 1:
                time.sleep(interval * (0.75 + random.random() * 0.5))
        return done

    def like_many_cards(
        self, friends: Iterable[str], times: int = 10, interval: float = 1.5
    ) -> list[tuple[str, int]]:
        result: list[tuple[str, int]] = []
        for fuin in friends:
            n = self.like_card(fuin, times=times, interval=interval)
            log.info("好友 %s 本次点赞 %d 次", fuin, n)
            result.append((str(fuin), n))
            time.sleep(interval * (0.75 + random.random() * 0.5))
        return result

    def list_feeds(self, num: int = 20, uin: str | None = None) -> list[dict[str, Any]]:
        """拉取某人空间的最新说说（默认自己，传 ``uin`` 就是好友的）。

        返回的每项都带好 ``unikey`` / ``curkey``，可以直接喂给 :meth:`like_feed`。
        """
        owner = str(uin or self.uin).strip()
        params = {
            "uin": owner,
            "ftype": 0,
            "sort": 0,
            "pos": 0,
            "num": num,
            "g_tk": self.gtk,
            "callback": "_Callback",
            "format": "jsonp",
        }
        resp = self._call("list_feeds", params=params)
        data = loads_js(resp.text)
        if not isinstance(data, dict):
            raise QzoneError("动态列表格式异常")
        if data.get("code") not in (0, None) and "msglist" not in data:
            raise QzoneError(f"拉取动态失败: code={data.get('code')} {data.get('message', '')}")
        feeds: list[dict[str, Any]] = []
        for item in data.get("msglist") or []:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("tid") or "")
            if not tid:
                continue
            # 新版接口不再返回 curkey/unikey，用 tid 约定式构造，接口认这个形式
            key = str(item.get("curkey") or "") or (
                f"http://user.qzone.qq.com/{owner}/mood/{tid}"
            )
            try:
                created = int(item.get("created_time") or 0)
            except (TypeError, ValueError):
                created = 0
            try:
                liked = int(item.get("liked") or 0)
            except (TypeError, ValueError):
                liked = 0
            feeds.append(
                {
                    "tid": tid,
                    "uin": owner,
                    "curkey": key,
                    "unikey": key,
                    "nick": str(item.get("name") or ""),
                    "content": str(item.get("content") or "")[:60],
                    "created_time": created,
                    "liked": liked,
                    "cmtnum": item.get("cmtnum") or 0,
                }
            )
        return feeds

    def like_feed(self, feed: dict[str, Any]) -> bool:
        """给一条动态点赞，返回是否成功（已赞也算成功）。"""
        data = {
            "opuin": self.uin,
            "unikey": feed.get("unikey", ""),
            "curkey": feed.get("curkey", ""),
            "dontadd": 0,
            "op": 1,
            "from": 1,
            "appid": 311,
            "format": "json",
            "qzreferrer": f"https://user.qzone.qq.com/{self.uin}",
        }
        resp = self._call("like_feed", params={"g_tk": self.gtk}, data=data, method="POST")
        payload = loads_js(resp.text)
        if not isinstance(payload, dict):
            return False
        # 新旧两种返回：{"ret":0,"msg":"succ"} / {"code":0,...}
        if payload.get("ret") == 0 or payload.get("code") == 0:
            return True
        # 已经赞过的情况直接算成功，避免重复请求被记成失败
        blob = json.dumps(payload, ensure_ascii=False)
        if "已经赞" in blob or "已赞" in blob:
            return True
        log.info("动态 %s 点赞失败: %s", feed.get("tid"), payload)
        return False


def _dry_feed_jsonp() -> str:
    """dry-run 用的假动态列表，时间取当前，保证能通过时间窗口过滤。"""
    payload = {
        "code": 0,
        "subcode": 0,
        "msglist": [
            {
                "tid": "dry-run-1",
                "curkey": "TID:dryrun1",
                "unikey": "http://user.qzone.qq.com/10001",
                "name": "示例好友",
                "content": "dry-run 动态",
                "created_time": int(time.time()),
                "liked": 0,
            }
        ],
    }
    return "_Callback(" + json.dumps(payload, ensure_ascii=False) + ");"
