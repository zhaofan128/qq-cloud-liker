# QQ 云端点赞机器人

跑在 GitHub Actions 上的 QQ 自动点赞服务：每天早上 10:00 给每位好友点满 10 个名片赞，另外常驻扫描空间动态、发出来就赞。

全程**不登录 QQ 客户端**，只复用浏览器的 Cookie 调网页接口 —— 所以任务执行时你手机 QQ 该在线就在线、该隐身就隐身，不会多出一台"电脑在线"的设备，也不会把手机挤下线。

```
┌──────────────────────── GitHub 仓库（你的） ────────────────────────┐
│                                                                     │
│  .github/workflows/daily-card-like.yml   每天 10:00（UTC 02:00）    │
│        └─> python main.py card-like  ──> 名片赞接口 ×10/好友        │
│                                                                     │
│  .github/workflows/feed-like.yml         每 5 分钟（兜底）          │
│        └─> python main.py feed-like  ──> 空间动态接口               │
│                                                                     │
│  Secrets: QQ_UIN / QQ_COOKIE    Variables: QQ_FRIENDS               │
└─────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ 同一套 Cookie
                              ▼
        ┌──────────── Cloudflare Worker（可选，真·实时）────────────┐
        │  Cron */1 * * * *  ──> 每分钟扫一次新动态                 │
        └───────────────────────────────────────────────────────────┘
```

## 两个任务

| 任务 | 做什么 | 触发时间 | 实现在哪 |
| --- | --- | --- | --- |
| **名片赞** | 给 `QQ_FRIENDS` 里每位好友点 **10 个赞**，就是截图里「赞了你 10 次」那个 | 每天 **北京时间 10:00** | GitHub Actions |
| **空间动态赞** | 扫描最新动态，给自己还没赞过的点赞 | **每 5 分钟**（Actions）/ **每分钟**（Worker） | Actions + Worker |

名片赞每人每天上限就是 10 次，脚本会点满 10 次后自动停；对方今天已经回赞过、或者不是好友，接口会返回错误码，脚本记一条日志然后跳过，不会卡死。

## 部署（约 5 分钟）

### 1. 建仓库

把本目录推到你的 GitHub 仓库。**建议设为 public** —— public 仓库的 Actions 完全免费，私有仓库每月只有 2000 分钟，跑每 5 分钟的任务会超额。Cookie 放在 Secrets 里，public 也看不到。

```bash
git init && git add . && git commit -m "init"
git remote add origin git@github.com:<你的用户名>/qq-cloud-liker.git
git push -u origin main
```

### 2. 抓 Cookie

1. 电脑浏览器打开 <https://user.qzone.qq.com> 并登录（扫码即可）。
2. 按 `F12` → **Network（网络）** → 刷新页面。
3. 点开任意一条 `user.qzone.qq.com` 的请求 → **Request Headers** → 复制整个 `Cookie:` 后面的字符串。
4. 必须包含 `uin=o0xxxxxx`、`skey=@xxxx`、`p_skey=xxxx` 这三项，缺 `p_skey` 会算不出 `g_tk`。

详细图文步骤见 [docs/SETUP.md](docs/SETUP.md)。

### 3. 配 Secrets 和 Variables

仓库 → **Settings** → **Secrets and variables** → **Actions**：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret | `QQ_UIN` | 你的 QQ 号（纯数字） |
| Secret | `QQ_COOKIE` | 上一步复制的整段 Cookie |
| Variable | `QQ_FRIENDS` | 好友 QQ 号，英文逗号分隔：`10001,10002,10003` |

好友也可以写在 `config/friends.txt`（每行一个），但 Variable 优先级更高。

### 4. 手动跑一次验证

仓库 → **Actions** → 选一个 workflow → **Run workflow**。

- 先跑 `每日名片赞`，把 `dry_run` 填 `1` 演练一遍，看日志有没有报错；
- 没问题再填 `0` 真跑；
- 打开 Actions 的 **Summary** 页，能看到「成功 / 跳过 / 失败」的表格和每个好友的明细。

## 关于「任务执行时 QQ 离线」

这一点是设计出来的，不是碰巧：

- 脚本**从不调用登录接口**，只带 Cookie 发普通 HTTPS 请求，QQ 服务端不会因此新建会话、不会产生登录设备记录。
- 好友列表里看到的你，仍然是你**手机 QQ 自己的状态**。想让别人看到"离线"，在手机 QQ 里把状态切成**隐身**就行 —— 隐身不影响 Cookie 调用，任务照跑。
- 反面教材：NapCat / Lagrange 这类协议端会真的登录一个"电脑端"，好友能看到在线，还可能把手机挤下线 —— 那跟你的需求正好相反，本方案没有用它。

## 实时性：三档选择

GitHub Actions 的 cron **最小 5 分钟，且高峰期经常延迟 3~15 分钟**，做不到"发出来就赞"。按需选：

| 方案 | 延迟 | 成本 | 适合 |
| --- | --- | --- | --- |
| Actions `*/5`（默认已配） | 5~20 分钟 | 免费（public 仓库） | 够用就行 |
| **Cloudflare Worker**（`worker/`） | ≤ 60 秒 | 免费额度足够 | 想要真·秒赞 |
| 自己的 VPS + 常驻进程 | 秒级 | 服务器钱 | 极致要求 |

Worker 部署：

```bash
cd worker
npm i -g wrangler
wrangler login
wrangler secret put QQ_UIN
wrangler secret put QQ_COOKIE
wrangler secret put TRIGGER_TOKEN   # 随便一串随机字符，防止别人调你的接口
wrangler deploy
```

Worker 只做动态点赞，**名片赞不放 Worker**：Cloudflare 免费版每次执行最多 50 个子请求，50 个好友 × 10 次 = 500 次，会直接超限。名片赞这种批量任务交给 Actions 才合适。

## 本地运行

```bash
pip install -r requirements.txt

export QQ_UIN=123456789
export QQ_COOKIE='uin=o0123456789; skey=@xxxx; p_skey=xxxx'
export QQ_FRIENDS=10001,10002

python main.py check                 # 校验 Cookie，打印昵称和 g_tk
python main.py card-like --times 10  # 名片赞
python main.py feed-like --since 120 # 只赞最近 2 小时的新动态
python main.py all --dry-run         # 不联网，演练全流程
```

`--dry-run` 用假数据跑完整流程，改代码后先跑它，再去真环境试。

## 风险与边界（请务必读完）

1. **这不是官方接口。** 名片赞、空间点赞都没有对外开放的 API，本项目用的是网页端私有接口，属于自动化操作，**违反 QQ 用户协议**，存在被限制点赞、限制登录甚至封号的可能。建议先用小号跑一周再上主号。
2. **Cookie 会过期。** 一般几天到几周。过期后 Actions 会红，日志里是「Cookie 已失效」，重新抓一次更新 Secret 即可。
3. **异地 IP 是最大的坑。** GitHub Actions 每次从不同的 Azure 机房 IP 出口，同一份 Cookie 频繁从多地访问，容易触发 QQ 的安全验证。所以脚本里所有请求都串行 + 随机间隔 1.5 秒左右，出一次错就跳过该好友，不做重试轰炸。如果你很在意稳定性，把名片赞放到固定 IP 的 VPS 上跑会明显更稳。
4. **Actions 定时任务在仓库 60 天无提交后会自动停用**，GitHub 会发邮件提醒，点一下就能恢复。
5. **不要提高频率。** `QQ_LIKE_INTERVAL` 调到 1 秒以下、或者把动态扫描降到每分钟以下，只会加速触发风控，收益为零。

## 接口改版了怎么办

QQ 前端一改版，私有接口就可能变。所有地址都集中在两个文件的 `ENDPOINTS` 常量里：

- Python：`qqliker/client.py`
- Worker：`worker/src/index.js`

出错时按这个顺序排查：

1. 浏览器登录空间，F12 看现在实际请求的是哪个 URL、哪些参数；
2. 替换 `ENDPOINTS` 里对应的一项；
3. 如果返回结构变了，改 `list_feeds` 里的字段映射（`tid / curkey / unikey / created_time / liked`）；
4. 跑 `python -m pytest tests -q`，再 `python main.py check`。

## 目录结构

```
qq-cloud-liker/
├── main.py                     CLI 入口：check / card-like / feed-like / all
├── qqliker/
│   ├── client.py               接口封装（ENDPOINTS 在这里）
│   ├── config.py               环境变量 → 配置
│   └── tasks.py                两个任务的编排与统计
├── .github/workflows/
│   ├── daily-card-like.yml     每天 10:00 名片赞
│   └── feed-like.yml           每 5 分钟动态赞
├── worker/                     Cloudflare 每分钟版（可选）
├── tests/                      不联网的单元测试
└── docs/SETUP.md               抓 Cookie 的详细步骤
```

## License

MIT。仅供个人学习自动化技术使用，使用后果自负。
