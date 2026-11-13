"""不联网的单元测试：验证 cookie 解析、g_tk、JSONP 解析和任务编排。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qqliker.client import QzoneClient, calc_gtk, loads_js, parse_cookies
from qqliker.tasks import run_card_like, run_feed_like

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """按 URL 关键字路由的假 session，同时记录调用。"""

    def __init__(self, routes: dict[str, FakeResp]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def _pick(self, url: str) -> FakeResp:
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return FakeResp('{"code":-1,"message":"no route"}')

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self._pick(url)

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self._pick(url)


def make_client(session, uin="10000"):
    return QzoneClient(
        uin,
        "uin=o010000; skey=@abcdefg; p_skey=ABCDEFG123456;",
        session=session,
        timeout=1,
    )


def test_parse_cookies():
    c = parse_cookies(" a=1; b=2 ;\n c=3=4 ")
    assert c["a"] == "1"
    assert c["b"] == "2"
    assert c["c"] == "3=4"


def test_calc_gtk_range_and_stability():
    g1 = calc_gtk("@abcdefg")
    g2 = calc_gtk("@abcdefg")
    assert g1 == g2
    assert 0 <= g1 < 2**31


def test_calc_gtk_matches_reference():
    """用独立写法（djb2 * 33）交叉验证。"""

    def ref(skey: str) -> int:
        h = 5381
        for ch in skey:
            h = (h * 33 + ord(ch)) % (2**32)
        return h & 0x7FFFFFFF

    for skey in ["@abc", "abcdefgh", "x" * 40]:
        assert calc_gtk(skey) == ref(skey)


def test_loads_js_jsonp_and_plain():
    assert loads_js('_Callback({"a":1});')["a"] == 1
    assert loads_js('{"a":2}')["a"] == 2


def test_loads_js_unquoted_keys():
    assert loads_js('_Callback({a:1,b:"x"});') == {"a": 1, "b": "x"}


def test_list_feeds_parsing():
    text = (FIXTURES / "msglist.js").read_text(encoding="utf-8")
    client = make_client(FakeSession({"emotion_cgi_msglist_v6": FakeResp(text)}))
    feeds = client.list_feeds(num=20)
    assert len(feeds) == 3
    assert feeds[0]["tid"] == "abc123"
    assert feeds[0]["liked"] == 0
    assert feeds[1]["liked"] == 1
    assert feeds[2]["created_time"] == 1730000000
    # 请求里带了 g_tk
    _, kwargs = client.s.calls[0]
    assert kwargs["params"]["g_tk"] == client.gtk


def test_like_card_success_then_limit():
    """前 3 次成功，第 4 次返回错误码后立即停止。"""
    seq = [
        FakeResp('{"code":0,"subcode":0}'),
        FakeResp('{"code":0,"subcode":0}'),
        FakeResp('{"code":0,"subcode":0}'),
        FakeResp('{"code":-10000,"message":"已达上限"}'),
    ]
    calls = {"i": 0}

    class SeqSession(FakeSession):
        def get(self, url, **kw):
            resp = seq[min(calls["i"], len(seq) - 1)]
            calls["i"] += 1
            self.calls.append((url, kw))
            return resp

    client = make_client(SeqSession({}))
    n = client.like_card("12345", times=10, interval=0)
    assert n == 3
    assert calls["i"] == 4


def test_like_card_sends_expected_params():
    session = FakeSession({"friend_ship_manager": FakeResp('{"code":0,"subcode":0}')})
    client = make_client(session)
    client.like_card("12345", times=1, interval=0)
    _, kwargs = session.calls[0]
    assert kwargs["params"]["fuin"] == "12345"
    assert kwargs["params"]["op"] == 1
    assert kwargs["params"]["g_tk"] == client.gtk


def test_run_card_like_aggregates():
    session = FakeSession({"friend_ship_manager": FakeResp('{"code":0,"subcode":0}')})
    client = make_client(session)
    report = run_card_like(client, ["1", "2"], times=2, interval=0)
    assert report.ok == 2
    assert report.failed == 0
    assert len(session.calls) == 4


def test_run_feed_like_only_recent_and_unliked():
    now = 1731500100
    payload = {
        "code": 0,
        "msglist": [
            {"tid": "new", "curkey": "TID:new", "unikey": "u1", "created_time": now - 60, "liked": 0, "name": "A"},
            {"tid": "liked", "curkey": "TID:liked", "unikey": "u2", "created_time": now - 60, "liked": 1, "name": "B"},
            {"tid": "old", "curkey": "TID:old", "unikey": "u3", "created_time": now - 99999, "liked": 0, "name": "C"},
        ],
    }
    session = FakeSession(
        {
            "emotion_cgi_msglist_v6": FakeResp("_Callback(" + json.dumps(payload) + ");"),
            "internal_dolike_app": FakeResp('{"code":0,"data":{"ret":0}}'),
        }
    )
    client = make_client(session)
    report = run_feed_like(client, num=20, since_minutes=120, max_like=10, interval=0, now=now)
    assert report.ok == 1
    assert report.skipped == 2
    like_calls = [c for c in session.calls if "internal_dolike_app" in c[0]]
    assert len(like_calls) == 1
    assert like_calls[0][1]["data"]["curkey"] == "TID:new"


def test_missing_skey_raises():
    with pytest.raises(Exception):
        QzoneClient("10000", "uin=o010000;")
