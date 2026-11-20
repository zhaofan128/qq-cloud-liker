/* Q赞 · 前端逻辑（纯静态，数据来自仓库与 GitHub API） */
(() => {
  const OWNER = 'zhaofan128';
  const REPO = 'qq-cloud-liker';
  const API = 'https://api.github.com';
  const BRANCH = 'main';

  const state = {
    snap: null,
    runs: [],
    enabled: new Set(),
    token: localStorage.getItem('qz_token') || '',
    filter: '',
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function toast(msg) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), 2200);
  }

  function ago(ts) {
    if (!ts) return '';
    const d = Math.floor(Date.now() / 1000 - ts);
    if (d < 60) return '刚刚';
    if (d < 3600) return `${Math.floor(d / 60)} 分钟前`;
    if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
    return `${Math.floor(d / 86400)} 天前`;
  }

  function fmtTime(iso) {
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  function ghHeaders() {
    const h = { Accept: 'application/vnd.github+json' };
    if (state.token) h.Authorization = `Bearer ${state.token}`;
    return h;
  }

  async function loadSnapshot() {
    // 加时间戳绕过缓存，保证看到最新快照
    const r = await fetch(`../data/snapshot.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!r.ok) throw new Error('快照读取失败');
    state.snap = await r.json();
    const cfg = state.snap.config || {};
    const all = (state.snap.friends || []).map((f) => f.uin);
    state.enabled = new Set(Array.isArray(cfg.enabled) ? cfg.enabled : all);
  }

  async function loadRuns() {
    try {
      const r = await fetch(`${API}/repos/${OWNER}/${REPO}/actions/runs?per_page=6`, { headers: ghHeaders() });
      if (!r.ok) return [];
      const d = await r.json();
      state.runs = (d.workflow_runs || []).filter((r) => /名片赞|动态秒赞/.test(r.name || ''));
    } catch {
      state.runs = [];
    }
    return state.runs;
  }

  function renderHeader() {
    const a = state.snap?.account || {};
    $('acct').textContent = a.name ? `${a.name} · ${a.uin}` : (a.uin || '未登录');
    const last = state.runs.find((x) => x.name && x.name.includes('名片赞'));
    const ok = last && last.conclusion === 'success';
    const st = $('status');
    st.className = 'pill' + (ok ? '' : ' off');
    st.innerHTML = `<i></i>${ok ? 'Cookie 有效' : (last ? '需检查' : '待执行')}`;
    $('loginV').textContent = ok ? '在线，Cookie 有效' : '需要重新获取 Cookie';
    $('loginNote').textContent = last
      ? `最近一次验证：${fmtTime(last.updated_at)}`
      : '还没有执行记录，去设置里手动跑一次';
  }

  function renderHome() {
    const friends = state.snap?.friends || [];
    const enabled = friends.filter((f) => state.enabled.has(f.uin)).length;
    const times = state.snap?.config?.times || 10;

    const today = new Date().toDateString();
    const doneToday = state.runs.some(
      (r) => r.name?.includes('名片赞') && new Date(r.created_at).toDateString() === today && r.conclusion === 'success'
    );
    $('todayNum').innerHTML = `${doneToday ? enabled * times : 0}<small>次</small>`;
    $('todaySub').textContent = doneToday
      ? `今天已完成 · ${enabled} 位好友 × ${times} 个`
      : `每天 10:00 自动执行 · ${enabled} 位好友 × ${times} 个`;
    $('fCount').innerHTML = `${enabled}<small>位</small>`;

    $('runCnt').textContent = state.runs.length ? `${state.runs.length} 条` : '—';
    const box = $('runs');
    if (!state.runs.length) {
      box.innerHTML = '<div class="empty"><div class="ic">·</div>暂无执行记录</div>';
      return;
    }
    box.innerHTML = state.runs.slice(0, 6).map((r) => {
      const ok = r.conclusion === 'success';
      const stat = r.status !== 'completed' ? '运行中' : ok ? '成功' : '失败';
      return `<div class="run ${ok ? 's' : r.status === 'completed' ? 'f' : ''}">
        <div class="dot"></div>
        <div><div class="t">${esc(r.name)}</div><div class="d">${fmtTime(r.created_at)}</div></div>
        <div class="st">${stat}</div>
      </div>`;
    }).join('');
  }

  function renderFriends() {
    const friends = state.snap?.friends || [];
    $('fCount2').textContent = `${friends.length} 位`;
    const kw = state.filter.trim().toLowerCase();
    const list = friends.filter(
      (f) => !kw || f.name.toLowerCase().includes(kw) || f.uin.includes(kw)
    );
    $('flist').innerHTML = list.length
      ? list.map((f) => {
          const on = state.enabled.has(f.uin);
          return `<div class="fitem" data-uin="${f.uin}">
            <div class="ava">${esc((f.name || '?').slice(0, 1))}</div>
            <div class="meta"><div class="n">${esc(f.name)}</div><div class="u">${f.uin}</div></div>
            <div class="sw ${on ? 'on' : ''}" data-uin="${f.uin}"></div>
          </div>`;
        }).join('')
      : '<div class="empty"><div class="ic">·</div>没有匹配的好友</div>';
  }

  function renderFeeds() {
    const feeds = state.snap?.feeds || [];
    const likes = state.snap?.likes || [];
    $('feedCnt').textContent = `${feeds.length} 条`;
    $('likeCnt').textContent = `${likes.length} 人`;

    $('feeds').innerHTML = feeds.length
      ? feeds.map((f) => `<div class="feed">
          <div class="top"><div class="nm">${esc(f.nick || '好友')}</div><div class="tm">${ago(f.time)}</div></div>
          <div class="ct">${esc(f.content) || '（无文字内容）'}</div>
        </div>`).join('')
      : '<div class="empty"><div class="ic">·</div>最近三天好友没有发动态</div>';

    $('likes').innerHTML = likes.length
      ? likes.map((l) => `<div class="fitem">
          <div class="ava">${esc((l.name || '?').slice(0, 1))}</div>
          <div class="meta"><div class="n">${esc(l.name)}</div><div class="u">赞了：${esc(l.feed) || '你的说说'}</div></div>
        </div>`).join('')
      : '<div class="empty"><div class="ic">·</div>暂时读不到点赞明细<br><span style="font-size:11.5px">QQ 网页端不开放名片赞记录</span></div>';
  }

  function renderAll() {
    renderHeader();
    renderHome();
    renderFriends();
    renderFeeds();
  }

  async function saveControl() {
    if (!state.token) {
      toast('已保存到本机（未填 Token，不会同步到云端）');
      return;
    }
    const body = {
      enabled: [...state.enabled],
      times: state.snap?.config?.times || 10,
    };
    const path = 'config/control.json';
    const url = `${API}/repos/${OWNER}/${REPO}/contents/${path}`;
    let sha;
    try {
      const g = await fetch(url, { headers: ghHeaders() });
      if (g.ok) sha = (await g.json()).sha;
    } catch {}
    const payload = {
      message: 'chore: 更新好友点赞配置',
      content: btoa(unescape(encodeURIComponent(JSON.stringify(body, null, 1)))),
      branch: BRANCH,
    };
    if (sha) payload.sha = sha;
    const r = await fetch(url, {
      method: 'PUT',
      headers: { ...ghHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    toast(r.ok ? '已同步到云端' : '同步失败，检查 Token 权限');
  }

  async function trigger(workflow) {
    if (!state.token) return toast('请先在设置里填写 GitHub Token');
    const r = await fetch(`${API}/repos/${OWNER}/${REPO}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: { ...ghHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: BRANCH }),
    });
    toast(r.status === 204 ? '已触发，约 30 秒后刷新' : '触发失败');
  }

  function bind() {
    document.querySelectorAll('.tab').forEach((t) => {
      t.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach((x) => x.classList.remove('on'));
        document.querySelectorAll('.view').forEach((x) => x.classList.remove('active'));
        t.classList.add('on');
        $('v-' + t.dataset.v).classList.add('active');
      });
    });

    $('q').addEventListener('input', (e) => {
      state.filter = e.target.value;
      renderFriends();
    });

    $('flist').addEventListener('click', (e) => {
      const sw = e.target.closest('.sw');
      if (!sw) return;
      const uin = sw.dataset.uin;
      if (state.enabled.has(uin)) state.enabled.delete(uin);
      else state.enabled.add(uin);
      sw.classList.toggle('on');
      clearTimeout(window._saveT);
      window._saveT = setTimeout(saveControl, 900);
    });

    $('allBtn').addEventListener('click', () => {
      const all = (state.snap?.friends || []).map((f) => f.uin);
      if (state.enabled.size === all.length) state.enabled.clear();
      else all.forEach((u) => state.enabled.add(u));
      renderFriends();
      saveControl();
    });

    $('saveTok').addEventListener('click', () => {
      const v = $('tok').value.trim();
      if (!v) return toast('请输入 Token');
      state.token = v;
      localStorage.setItem('qz_token', v);
      $('tok').value = '';
      toast('Token 已保存');
      loadRuns().then(renderAll);
    });

    $('runCard').addEventListener('click', () => trigger('daily-card-like.yml'));
    $('runFeed').addEventListener('click', () => trigger('feed-like.yml'));
  }

  async function init() {
    bind();
    if (state.token) $('tok').placeholder = '已保存，可重新输入覆盖';
    try {
      await loadSnapshot();
    } catch (e) {
      toast('数据加载失败');
    }
    await loadRuns();
    renderAll();
    // 后台静默刷新一次执行记录
    setTimeout(async () => {
      await loadRuns();
      renderAll();
    }, 4000);
  }

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
  init();
})();
