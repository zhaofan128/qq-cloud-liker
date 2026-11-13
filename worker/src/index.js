/**
 * QQ 空间动态「秒赞」Worker（Cloudflare）
 *
 * 为什么不全放 GitHub Actions：
 *   Actions 的 schedule 最小粒度 5 分钟且经常延迟，做不到"发出来就赞"。
 *   Worker 的 Cron Trigger 支持每分钟一次，正好补上这块。
 *
 * 为什么 Worker 只做动态点赞、不做名片赞：
 *   Cloudflare 免费版每次 invocation 最多 50 个子请求，
 *   50 个好友 × 10 次 = 500 次请求，会直接超限。
 *   名片赞这种耗时任务留给 GitHub Actions（无子请求限制）。
 */

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const ENDPOINTS = {
  listFeeds:
    "https://h5.qzone.qq.com/proxy/domain/taotao.qq.com/cgi-bin/emotion_cgi_msglist_v6",
  likeFeed:
    "https://h5.qzone.qq.com/proxy/domain/w.qzone.qq.com/cgi-bin/likes/internal_dolike_app",
};

function calcGtk(skey) {
  let h = 5381;
  for (let i = 0; i < skey.length; i++) {
    h = (h * 33 + skey.charCodeAt(i)) % 4294967296;
  }
  return h & 0x7fffffff;
}

function parseCookies(cookie) {
  const out = {};
  for (const seg of String(cookie || "").replace(/\n/g, ";").split(";")) {
    const i = seg.indexOf("=");
    if (i < 0) continue;
    out[seg.slice(0, i).trim()] = seg.slice(i + 1).trim();
  }
  return out;
}

function loadsJs(text) {
  let s = String(text || "").trim();
  const m = s.match(/^[\w$.]+\(([\s\S]*)\)\s*;?\s*$/);
  if (m) s = m[1];
  return JSON.parse(s);
}

function baseHeaders(env) {
  return {
    "User-Agent": UA,
    Cookie: env.QQ_COOKIE,
    Referer: `https://user.qzone.qq.com/${env.QQ_UIN}`,
    Accept: "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
  };
}

function gtkOf(env) {
  const c = parseCookies(env.QQ_COOKIE);
  return calcGtk(c.p_skey || c.skey || "");
}

async function listFeeds(env, num) {
  const url = new URL(ENDPOINTS.listFeeds);
  const params = {
    uin: env.QQ_UIN,
    ftype: "0",
    sort: "0",
    pos: "0",
    num: String(num),
    g_tk: String(gtkOf(env)),
    callback: "_Callback",
    format: "jsonp",
  };
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const resp = await fetch(url.toString(), { headers: baseHeaders(env) });
  if (!resp.ok) throw new Error(`listFeeds HTTP ${resp.status}`);
  const data = loadsJs(await resp.text());
  return (data.msglist || []).filter((m) => m && m.curkey);
}

async function likeFeed(env, feed) {
  const body = new URLSearchParams({
    opuin: String(env.QQ_UIN),
    unikey: feed.unikey || "",
    curkey: feed.curkey || "",
    dontadd: "0",
    op: "1",
    from: "1",
    appid: "311",
    format: "json",
    qzreferrer: `https://user.qzone.qq.com/${env.QQ_UIN}`,
  });
  const url = `${ENDPOINTS.likeFeed}?g_tk=${gtkOf(env)}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { ...baseHeaders(env), "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!resp.ok) return false;
  const data = loadsJs(await resp.text());
  return data && data.code === 0;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function runFeedLike(env, sinceMinutes = 120, maxLike = 10) {
  const feeds = await listFeeds(env, 20);
  const cutoff = Date.now() / 1000 - sinceMinutes * 60;
  const pending = feeds.filter(
    (f) => !Number(f.liked || 0) && Number(f.created_time || 0) >= cutoff
  );
  const result = { scanned: feeds.length, pending: pending.length, liked: 0, failed: 0 };
  for (const feed of pending.slice(0, maxLike)) {
    const ok = await likeFeed(env, feed);
    ok ? result.liked++ : result.failed++;
    await sleep(1500);
  }
  return result;
}

export default {
  async scheduled(event, env, ctx) {
    const since = Number(env.SINCE_MINUTES || 120);
    const res = await runFeedLike(env, since, 10);
    console.log(`[cron ${event.cron}] ${JSON.stringify(res)}`);
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (env.TRIGGER_TOKEN && url.searchParams.get("token") !== env.TRIGGER_TOKEN) {
      return new Response("forbidden", { status: 403 });
    }
    if (url.pathname !== "/run") {
      return new Response(
        "qq-feed-liker is running.\n手动触发: /run?token=YOUR_TOKEN",
        { headers: { "content-type": "text/plain; charset=utf-8" } }
      );
    }
    try {
      const res = await runFeedLike(env, Number(url.searchParams.get("since") || 120), 10);
      return Response.json(res);
    } catch (err) {
      return Response.json({ error: String(err) }, { status: 500 });
    }
  },
};
