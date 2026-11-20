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
        FakeResp('{"code":0,"subcode":0,"message":"succ"}'),
        FakeResp('{"code":0,"subcode":0,"message":"succ"}'),
        FakeResp('{"code":0,"subcode":0,"message":"succ"}'),
        FakeResp('{"code":-10000,"message":"已达上限"}'),
    ]
    calls = {"i": 0}

    class SeqSession(FakeSession):
        def post(self, url, **kw):
            resp = seq[min(calls["i"], len(seq) - 1)]
            calls["i"] += 1
            self.calls.append((url, kw))
            return resp

        def get(self, url, **kw):  # pragma: no cover - 不应被调用
            raise AssertionError("like_card 应该只发 POST")

    client = make_client(SeqSession({}))
    n = client.like_card("12345", times=10, interval=0)
    assert n == 3
    assert calls["i"] == 4


def test_like_card_sends_expected_params():
    session = FakeSession({"internal_dolike_app": FakeResp('{"code":0,"message":"succ"}')})
    client = make_client(session)
    client.like_card("12345", times=1, interval=0)
    url, kwargs = session.calls[0]
    assert "internal_dolike_app" in url
    assert kwargs["params"]["g_tk"] == client.gtk
    assert kwargs["data"]["appid"] == 7030
    assert kwargs["data"]["unikey"] == "http://user.qzone.qq.com/12345"
    assert kwargs["data"]["curkey"] == "http://user.qzone.qq.com/12345"
    assert kwargs["data"]["op"] == 1
    assert kwargs["data"]["opuin"] == "10000"


def test_card_likeable_today_reads_page_flag():
    page = '<script>g_likeable_today=+"0", g_moreModules=[]</script>'
    client = make_client(FakeSession({"https://user.qzone.qq.com/12345": FakeResp(page)}))
    assert client.card_likeable_today("12345") == 0
    client2 = make_client(FakeSession({"https://user.qzone.qq.com/12345": FakeResp('g_likeable_today=+"1"')}))
    assert client2.card_likeable_today("12345") == 1


def test_run_card_like_aggregates():
    """两位好友：都还没赞过，各点 2 次；赞完状态变 0 记作已验证。"""
    liked: set[str] = set()

    class StateSession(FakeSession):
        def _pick(self, url: str) -> FakeResp:
            if "internal_dolike_app" in url:
                return FakeResp('{"code":0,"subcode":0,"message":"succ"}')
            # 主页：根据是否赞过返回 g_likeable_today
            fuin = url.rstrip("/").rsplit("/", 1)[-1]
            return FakeResp('g_likeable_today=+"%d"' % (0 if fuin in liked else 1))

        def post(self, url, **kw):
            self.calls.append((url, kw))
            fuin = kw["data"]["unikey"].rstrip("/").rsplit("/", 1)[-1]
            liked.add(fuin)
            return self._pick(url)

    session = StateSession({})
    client = make_client(session)
    report = run_card_like(client, ["1", "2"], times=2, interval=0)
    assert report.ok == 2
    assert report.failed == 0
    assert report.skipped == 0
    assert "已验证" in " ".join(report.details)
    # 2 次点赞 × 2 人 + 每人 2 次主页查询
    assert len([c for c in session.calls if "internal_dolike_app" in c[0]]) == 4
    assert len([c for c in session.calls if "internal_dolike_app" not in c[0]]) == 4


def test_run_feed_like_only_recent_and_unliked():
    now = 1731500100
    payload = {
        "code": 0,
        "msglist": [
            {"tid": "new", "created_time": now - 60, "liked": 0, "name": "A"},
            {"tid": "liked", "created_time": now - 60, "liked": 1, "name": "B"},
            {"tid": "old", "created_time": now - 99999, "liked": 0, "name": "C"},
        ],
    }
    session = FakeSession(
        {
            "emotion_cgi_msglist_v6": FakeResp("_Callback(" + json.dumps(payload) + ");"),
            "internal_dolike_app": FakeResp('{"ret":0,"msg":"succ"}'),
        }
    )
    client = make_client(session)
    report = run_feed_like(
        client, ["12345"], num=3, since_minutes=15, max_like=10, interval=0, now=now
    )
    assert report.ok == 1
    assert report.failed == 0
    like_calls = [c for c in session.calls if "internal_dolike_app" in c[0]]
    assert len(like_calls) == 1
    # 关键：unikey 里应该是"好友的"QQ，不是自己
    assert like_calls[0][1]["data"]["curkey"] == "http://user.qzone.qq.com/12345/mood/new"


def test_missing_skey_raises():
    with pytest.raises(Exception):
        QzoneClient("10000", "uin=o010000;")
