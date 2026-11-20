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
    schedule: localStorage.getItem('qz_schedule') || '10:00',
    times: Number(localStorage.getItem('qz_times') || 10),
    dirty: false,
  };

  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (!localStorage.getItem('qz_install_hide') && !isStandalone()) {
      document.getElementById('installBar')?.classList.add('show');
    }
  });

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
    if (!state.dirty) {
      if (typeof cfg.schedule === 'string' && /^\d{2}:\d{2}$/.test(cfg.schedule)) state.schedule = cfg.schedule;
      if (cfg.times) state.times = Number(cfg.times);
    }
  }

  /* ---- 定时时间与 UTC cron 互转 ---- */
  function toCron(hhmm) {
    const [h, m] = String(hhmm).split(':').map(Number);
    const utcH = ((h - 8) % 24 + 24) % 24; // 北京时间 UTC+8
    return `${m || 0} ${utcH} * * *`;
  }

  function fromCron(cron) {
    const m = String(cron).trim().split(/\s+/);
    if (m.length < 2) return null;
    const mm = Number(m[0]);
    const hh = Number(m[1]);
    if (Number.isNaN(mm) || Number.isNaN(hh)) return null;
    const local = ((hh + 8) % 24 + 24) % 24;
    return `${String(local).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  }

  async function loadRuns() {
    const cached = (state.snap?.runs || []).filter((r) => /名片赞|空间赞|动态秒赞/.test(r.name || ''));
    if (cached.length) {
      state.runs = cached;
      return cached;
    }
    try {
      const r = await fetch(`${API}/repos/${OWNER}/${REPO}/actions/runs?per_page=6`, { headers: ghHeaders() });
      if (!r.ok) return [];
      const d = await r.json();
      state.runs = (d.workflow_runs || []).filter((r) => /名片赞|空间赞|动态秒赞/.test(r.name || ''));
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
    if (!last) {
      st.className = 'pill off';
      st.innerHTML = '<i></i>待检测';
      $('loginV').textContent = '暂无执行记录';
      $('loginNote').textContent = state.token
        ? '去设置里手动跑一次，或等下一次定时任务'
        : '在设置里填 Token 后可读取实时状态';
      return;
    }
    st.className = 'pill' + (ok ? '' : ' off');
    st.innerHTML = `<i></i>${ok ? 'Cookie 有效' : '需检查'}`;
    $('loginV').textContent = ok ? '离线运行 · Cookie 有效' : '需要重新获取 Cookie';
    $('loginNote').textContent = `最近一次验证：${fmtTime(last.updated_at || last.created_at)}`;
  }

  function renderHome() {
    const friends = state.snap?.friends || [];
    const enabled = friends.filter((f) => state.enabled.has(f.uin)).length;
    const times = state.times || 10;

    const today = new Date().toDateString();
    // 用最近一次「名片赞」任务的真实结果，而不是拿配置估算
    const lastCard = state.runs.find(
      (r) => r.name?.includes('名片赞') && r.status === 'completed'
    );
    const cardToday = lastCard && new Date(lastCard.created_at).toDateString() === today;
    const okFriends = Number(lastCard?.ok || 0);
    const skippedFriends = Number(lastCard?.skipped || 0);
    $('todayNum').innerHTML = `${cardToday ? okFriends * times : 0}<small>次</small>`;
    $('todaySub').textContent = cardToday
      ? `今天已赞 ${okFriends} 位好友${skippedFriends ? `，${skippedFriends} 位今天已赞过` : ''}`
      : `每天 ${state.schedule} 自动执行 · ${enabled} 位好友 × ${times} 个`;
    $('fCount').innerHTML = `${enabled}<small>位</small>`;

    $('runCnt').textContent = state.runs.length ? `${state.runs.length} 条` : '—';
    const box = $('runs');
    if (!state.runs.length) {
      box.innerHTML = `<div class="empty"><div class="ic">·</div>暂无执行记录<br><span style="font-size:11.5px">${
        state.token ? '等下一次任务，或去设置里手动执行' : '在设置里填 Token 可读取实时记录'
      }</span></div>`;
      return;
    }
    box.innerHTML = state.runs.slice(0, 6).map((r) => {
      const ok = r.conclusion === 'success';
      const stat = r.status !== 'completed' ? '运行中' : ok ? '成功' : '失败';
      return `<div class="run ${ok ? 's' : r.status === 'completed' ? 'f' : ''}">
        <div class="dot"></div>
        <div><div class="t">${esc(r.name)}</div><div class="d">${fmtTime(r.created_at)}${
          r.ok != null ? ` · ${r.ok} 人` : ''
        }${r.skipped ? ` · 跳过 ${r.skipped}` : ''}</div></div>
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
    renderSettings();
  }

  const b64enc = (str) => btoa(unescape(encodeURIComponent(str)));
  const b64dec = (s) => decodeURIComponent(escape(atob(String(s).replace(/\s/g, ''))));

  async function getFile(path) {
    const url = `${API}/repos/${OWNER}/${REPO}/contents/${path}?ref=${BRANCH}`;
    const r = await fetch(url, { headers: ghHeaders(), cache: 'no-store' });
    if (!r.ok) return null;
    const d = await r.json();
    return { sha: d.sha, text: b64dec(d.content || '') };
  }

  async function putFile(path, text, message) {
    const cur = await getFile(path);
    const payload = {
      message,
      content: b64enc(text),
      branch: BRANCH,
    };
    if (cur?.sha) payload.sha = cur.sha;
    const r = await fetch(`${API}/repos/${OWNER}/${REPO}/contents/${path}`, {
      method: 'PUT',
      headers: { ...ghHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return r.ok;
  }

  async function pushControl() {
    const body = {
      enabled: [...state.enabled],
      times: state.times,
      schedule: state.schedule,
    };
    return putFile('config/control.json', JSON.stringify(body, null, 1) + '\n', 'chore: 更新点赞配置');
  }

  async function saveControl() {
    localStorage.setItem('qz_times', String(state.times));
    if (!state.token) {
      toast('已保存到本机（未填 Token，不会同步到云端）');
      return;
    }
    const ok = await pushControl();
    toast(ok ? '已同步到云端' : '同步失败，检查 Token 权限');
  }

  /* 改定时：同时改 cron 与配置文件 */
  async function saveSchedule() {
    const t = $('schTime').value || '10:00';
    const n = Math.max(1, Math.min(20, Number($('schTimes').value) || 10));
    state.schedule = t;
    state.times = n;
    localStorage.setItem('qz_schedule', t);
    localStorage.setItem('qz_times', String(n));
    state.dirty = true;

    if (!state.token) {
      toast('已存到本机；填 Token 后才能改云端时间');
      renderHome();
      renderSettings();
      return;
    }

    const btn = $('saveSch');
    btn.disabled = true;
    btn.textContent = '同步中…';

    try {
      const wf = '.github/workflows/daily-card-like.yml';
      const cur = await getFile(wf);
      if (!cur) throw new Error('读不到 workflow');
      const cron = toCron(t);
      const next = cur.text.replace(/^(\s*-\s*cron:\s*)["'][^"']*["']/m, `$1"${cron}"`);
      if (next === cur.text && !cur.text.includes(`"${cron}"`)) throw new Error('cron 替换失败');

      const ok1 = await putFile(wf, next, `chore: 名片赞改为每天 ${t}（北京时间）`);
      const ok2 = await pushControl();
      if (!ok1 || !ok2) throw new Error('写入失败');

      toast(`已改为每天 ${t}，下一轮生效`);
      state.dirty = false;
    } catch (e) {
      toast(String(e.message || e));
    } finally {
      btn.disabled = false;
      btn.textContent = '保存并同步到云端';
      renderHome();
      renderSettings();
    }
  }

  function renderSettings() {
    const st = $('schTime');
    if (st && document.activeElement !== st) st.value = state.schedule;
    const nt = $('schTimes');
    if (nt && document.activeElement !== nt) nt.value = state.times;
    const badge = $('schState');
    if (badge) badge.textContent = `每天 ${state.schedule}`;
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
    $('saveSch').addEventListener('click', saveSchedule);

    // 安装到桌面
    const bar = $('installBar');
    if (!localStorage.getItem('qz_install_hide') && !isStandalone()) bar.classList.add('show');
    $('installX').addEventListener('click', () => {
      bar.classList.remove('show');
      localStorage.setItem('qz_install_hide', '1');
    });
    $('installBtn').addEventListener('click', async () => {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        await deferredPrompt.userChoice;
        deferredPrompt = null;
        bar.classList.remove('show');
        return;
      }
      const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
      toast(ios ? 'Safari 底部「分享」→ 添加到主屏幕' : '浏览器菜单 → 添加到主屏幕');
    });
  }

  function isStandalone() {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true
    );
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
