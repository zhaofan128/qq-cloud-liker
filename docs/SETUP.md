# 部署与排错手册

## 一、抓 Cookie（最关键的一步）

Cookie 相当于你的登录凭证，脚本靠它冒充"已登录的浏览器"。

### 步骤

1. **用电脑**打开 Chrome / Edge，访问 <https://user.qzone.qq.com>，扫码登录。
2. 按 `F12` 打开开发者工具，切到 **Network / 网络** 面板，勾选 **Preserve log / 保留日志**。
3. 按 `F5` 刷新页面。
4. 在请求列表里点任意一条发往 `user.qzone.qq.com` 的请求（比如 `Portal` 或 `infocenter`）。
5. 右侧 **Headers → Request Headers**，找到 `Cookie:`，把冒号后面**整段**复制出来。
6. 检查里面是否有这三项：

```
uin=o0123456789;        ← 你的 QQ 号（前面带 o0）
skey=@AbCdEfGh;         ← 短期票据
p_skey=AbCdEfGhIjKl;    ← 空间专用票据，g_tk 靠它算
```

> ⚠️ 只复制 `user.qzone.qq.com` 请求里的 Cookie。如果你复制的是 `qun.qq.com` 或 `mail.qq.com` 的，`p_skey` 是另一个域的，算出来的 `g_tk` 对不上，接口会一律返回失败。

### 手机没电脑怎么办

用手机浏览器打开 <https://user.qzone.qq.com>（不是 QQ 客户端内置浏览器），登录后地址栏执行 `javascript:` 书签的方式较麻烦，推荐直接借一台电脑，或者用 Kiwi Browser + 开发者工具。

## 二、配置 GitHub

| 位置 | 名称 | 说明 |
| --- | --- | --- |
| Settings → Secrets → Actions | `QQ_UIN` | 纯数字 QQ 号 |
| Settings → Secrets → Actions | `QQ_COOKIE` | 整段 Cookie（含分号） |
| Settings → Variables → Actions | `QQ_FRIENDS` | `10001,10002,10003` |

Cookie 里有 `;` `@` `,` 等字符，**不要加引号**，直接粘贴整段即可，Secrets 会原样保存。

## 三、时间怎么改

GitHub Actions 的 cron 是 **UTC**，比北京时间晚 8 小时。

| 你想要（北京时间） | cron 写法（UTC） |
| --- | --- |
| 每天 10:00 | `0 2 * * *` |
| 每天 08:00 | `0 0 * * *` |
| 每天 00:00 | `0 16 * * *`（前一天 UTC） |
| 每 30 分钟 | `*/30 * * * *` |

改完记得把「触发时间」注释一起改掉，不然三个月后自己都看不懂。

> GitHub 的 schedule 在高峰期会延迟，10:00 的任务实际可能在 10:05~10:20 之间触发，这是平台行为，无法避免。

## 四、排错对照表

| 日志现象 | 原因 | 处理 |
| --- | --- | --- |
| `Cookie 里没有 skey / p_skey` | 复制的是别的域的 Cookie | 重新从 `user.qzone.qq.com` 抓 |
| `Cookie 已失效，需要重新获取` | Cookie 过期 | 重抓并更新 Secret |
| 好友全是 `0（已达上限/非好友）` | 今天已经赞过 / 对方不是双向好友 / 被风控 | 换小号对比，或明天再试 |
| `拉取动态失败: code=-3000` | `g_tk` 不对或 Cookie 半失效 | 重抓 Cookie |
| `无法解析响应` | 接口返回结构变了 | 按 README「接口改版了怎么办」排查 |
| Actions 不自动跑了 | 仓库 60 天无提交被停用 | Actions 页面点 Enable |
| 每次都是 `HTTP 403` | 出口 IP 被拦 | 降低频率，或改用 VPS |

## 五、验证顺序（照这个来，少走弯路）

```bash
# 1. 先验 Cookie 通不通
python main.py check

# 2. 不联网演练，确认配置读对了
python main.py all --dry-run

# 3. 只给一个好友点 1 次，最小成本验证接口
python main.py card-like --friends 10001 --times 1

# 4. 确认没问题再放开
python main.py card-like --times 10
```

在 Actions 里对应操作：先 `dry_run=1` 手动跑，看 Summary 页的表格，再 `dry_run=0`。

## 六、Cookie 续期

Cookie 过期是常态，不是 bug。建议：

- 把「更新 Cookie」加进手机日历，每两周提醒一次；
- 失败时 Actions 会显示红色 ✗ 并发出邮件，看到就更新；
- 想彻底免维护只能上扫码登录（需要 NTQQ 客户端 + 一台常开的机器），GitHub Actions 跑不了 GUI 客户端，本项目没有做这条路线。
