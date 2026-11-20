"""两个任务的具体编排：名片赞 + 空间动态点赞。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .client import QzoneClient

log = logging.getLogger("qqliker.tasks")


@dataclass
class TaskReport:
    name: str
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.details.append(msg)

    def render(self) -> str:
        lines = [
            f"任务: {self.name}",
            f"成功 {self.ok} / 跳过 {self.skipped} / 失败 {self.failed}",
        ]
        lines.extend("  - " + d for d in self.details)
        return "\n".join(lines)


def run_card_like(
    client: QzoneClient,
    friends: list[str],
    times: int = 10,
    interval: float = 1.5,
    max_friends: int = 0,
) -> TaskReport:
    """给每位好友的空间主页点 ``times`` 个赞（备注：这是空间赞，不是手机QQ 的名片赞）。

    每位好友点赞前后各查一次空间主页的 ``g_likeable_today``：
    赞之前已经是 0 说明今天赞过了，直接跳过；赞之后再查一次确认真点上去了，
    避免接口"假成功"。
    """
    report = TaskReport(name="空间赞")
    targets = friends[:max_friends] if max_friends else friends
    if not targets:
        report.add("未配置好友列表（QQ_FRIENDS 或 config/friends.txt）")
        return report
    for i, fuin in enumerate(targets, 1):
        log.info("[%d/%d] 给好友 %s 点赞 …", i, len(targets), fuin)
        try:
            before = client.card_likeable_today(fuin)
        except Exception:
            before = None
        if before == 0:
            report.skipped += 1
            report.add(f"{fuin}: 今天已经赞过，跳过")
            continue
        try:
            n = client.like_card(fuin, times=times, interval=interval)
        except Exception as exc:  # 单点失败不中断整体
            report.failed += 1
            report.add(f"{fuin}: 异常 {exc}")
            continue
        if n <= 0:
            report.skipped += 1
            report.add(f"{fuin}: 0（已达上限/非好友/Cookie 问题）")
            continue
        report.ok += 1
        try:
            after = client.card_likeable_today(fuin)
        except Exception:
            after = None
        tag = "已验证" if after == 0 else ("未确认" if after is None else "可疑")
        report.add(f"{fuin}: +{n} {tag}")
        if i < len(targets):
            time.sleep(interval)
    return report


def run_feed_like(
    client: QzoneClient,
    friends: list[str],
    num: int = 2,
    since_minutes: int = 15,
    max_like: int = 20,
    interval: float = 1.5,
    max_friends: int = 0,
    now: float | None = None,
) -> TaskReport:
    """扫好友空间的最新说说，给 ``since_minutes`` 分钟内、还没赞过的点个赞。

    之前那版拉的是自己空间的说说（等于白赞），这里改成逐个好友取最新几条。
    """
    report = TaskReport(name="空间动态点赞")
    targets = friends[:max_friends] if max_friends else friends
    if not targets:
        report.add("未配置好友列表（QQ_FRIENDS 或 config/friends.txt）")
        return report

    cutoff = (now or time.time()) - since_minutes * 60
    pending: list[dict[str, Any]] = []
    for fuin in targets:
        try:
            feeds = client.list_feeds(num=num, uin=fuin)
        except Exception as exc:
            log.info("好友 %s 说说拉取失败: %s", fuin, exc)
            continue
        for f in feeds:
            if int(f.get("created_time") or 0) >= cutoff and not f.get("liked"):
                pending.append(f)
        time.sleep(0.15)

    log.info("扫了 %d 位好友，%d 分钟内的新说说 %d 条", len(targets), since_minutes, len(pending))
    if not pending:
        report.add(f"最近 {since_minutes} 分钟没有新说说")
        return report

    for feed in pending[:max_like]:
        who = feed.get("nick") or feed.get("uin")
        try:
            if client.like_feed(feed):
                report.ok += 1
                report.add(f"{who}: 已赞 {(feed.get('content') or '')[:12]}")
            else:
                report.failed += 1
                report.add(f"{who}/{feed.get('tid')}: 点赞失败")
        except Exception as exc:
            report.failed += 1
            report.add(f"{who}/{feed.get('tid')}: 异常 {exc}")
        time.sleep(interval)
    return report
