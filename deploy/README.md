# 云端名片赞（NapCat + 每日自动 send_like）

手机 QQ 里的「名片赞」只能通过 QQ 协议端来做，网页 Cookie 接口做不到。
这个目录就是协议端方案：一台 **7×24 在云的容器** 登录你的 QQ，每天 10:00
调 OneBot 的 `send_like`，给每位好友点满 10 个名片赞。不用电脑、不用手机常开。

---

## 部署（手机也能做，约 8 分钟）

### 1. 打开 ClawCloud Run

<https://console.run.claw.cloud>

点 `Get started for free`，选 **Continue with GitHub** 登录。
GitHub 账号满 180 天会送每月 5 美元额度，够跑这一台容器，不用绑卡。

### 2. 建应用

左侧 **App Launchpad** → **Create App**，只填这几个：

| 字段 | 填什么 |
| --- | --- |
| Application Name | `qq-like` |
| Image Name | `mlikiowa/napcat-docker:latest` |
| Usage | `0.5` 核 / `1` GB |
| Network | 添加 TCP 端口 `6099`（可选，用来进网页面板） |

**Local Storage（持久化，一定要加，否则重启就要重新扫码）**

| 挂载路径 | 大小 |
| --- | --- |
| `/app/napcat` | 1 GB |
| `/app/.config/QQ` | 2 GB |

区域选 **Singapore** 或 **Japan**（离国内近）。

点 **Deploy**，等状态变成 Running。

### 3. 扫码登录

进应用详情 → **Logs**，日志里会打印一个大二维码，也可能给出
`二维码解码URL`。用手机 QQ 右上角 `+` → 扫一扫，点确认登录。

> 二维码 2 分钟过期。过期就在应用详情里点 **Restart**，日志会刷新出新二维码。

### 4. 装点赞脚本

应用详情 → **Terminal**，粘贴回车：

```bash
curl -fsSL https://raw.githubusercontent.com/zhaofan128/qq-cloud-liker/main/deploy/setup.sh | bash
```

它会写好接口配置、放好点赞脚本。第一次跑会提示**需要重启一次**：

1. 回应用详情点 **Restart**
2. 重启完再进 Terminal，**再执行一次同一条命令**

第二次会打印 `daily liker started`，说明后台常驻已经起来，每天 10:00
（北京时间）给全部好友各点 10 个赞。

> 如果 Create App 的表单里有 **Command / 启动命令** 字段，直接填下面这行，
> 就能跳过上面两次执行，部署完即生效：
>
> ```bash
> bash -c "curl -fsSL https://raw.githubusercontent.com/zhaofan128/qq-cloud-liker/main/deploy/boot.sh -o /tmp/b.sh && bash /tmp/b.sh"
> ```

### 5. 立刻验证一次

同一个终端里：

```bash
python3 /app/dailylike.py --once
```

会打印每位好友的成功/跳过情况，并写进 `data/runs.json`（回传到 GitHub，App 首页能看到）。

---

## 环境变量（可选）

在 ClawCloud 应用设置里加：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LIKE_AT` | `10:00` | 每天几点执行（UTC+8） |
| `LIKE_TIMES` | `10` | 每人每天几个赞，QQ 上限 10 |
| `LIKE_GAP` | `1.2` | 好友之间的间隔秒数 |
| `MAX_FRIENDS` | `0` | 只点前 N 位，0 = 全部 |
| `GITHUB_TOKEN` | 空 | 填了才会把执行记录回传仓库 |
| `GITHUB_REPO` | 空 | 例如 `zhaofan128/qq-cloud-liker` |

---

## 说明

- 协议端登录后 QQ 处于**在线**状态。脚本启动时会尽量切成**隐身**，
  好友看不到你在线上，但腾讯后台能看到这个号挂着。
- 非官方协议有极小概率触发风控。不要高频调用，`LIKE_GAP` 别调到 1 以下。
- 每人每天上限 10 个是腾讯限制，脚本已经按 10 发。
- 容器重装/换平台后需要重新扫码，登录态在持久卷里。
