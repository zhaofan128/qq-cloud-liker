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
    """给每位好友的名片点 ``times`` 个赞（QQ 每人每天上限 10 个）。

    每位好友点赞前后各查一次空间主页的 ``g_likeable_today``：
    赞之前已经是 0 说明今天赞过了，直接跳过；赞之后再查一次确认真点上去了，
    避免接口"假成功"。
    """
    report = TaskReport(name="名片赞")
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
    num: int = 20,
    since_minutes: int = 120,
    max_like: int = 10,
    interval: float = 2.0,
    now: float | None = None,
) -> TaskReport:
    """给最近 ``since_minutes`` 分钟内、自己还没赞过的动态点赞。"""
    report = TaskReport(name="空间动态点赞")
    feeds: list[dict[str, Any]] = client.list_feeds(num=num)
    if not feeds:
        report.add("没有拉到动态（空间为空或接口变动）")
        return report

    cutoff = (now or time.time()) - since_minutes * 60
    pending = [f for f in feeds if not f.get("liked") and int(f.get("created_time") or 0) >= cutoff]
    report.skipped += len(feeds) - len(pending)
    log.info("共 %d 条动态，待赞 %d 条", len(feeds), len(pending))

    for feed in pending[:max_like]:
        try:
            if client.like_feed(feed):
                report.ok += 1
                report.add(f"{feed.get('nick') or feed.get('tid')}: 已赞")
            else:
                report.failed += 1
                report.add(f"{feed.get('tid')}: 点赞失败")
        except Exception as exc:
            report.failed += 1
            report.add(f"{feed.get('tid')}: 异常 {exc}")
        time.sleep(interval)
    return report
