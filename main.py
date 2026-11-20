#!/usr/bin/env python3
"""命令行入口。

用法示例::

    python main.py check                     # 校验 Cookie 是否有效
    python main.py card-like --times 10      # 给每位好友点 10 个名片赞
    python main.py feed-like --since 120     # 给最近 2 小时的动态点赞
    python main.py all                       # 两个任务都跑
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from qqliker.client import QzoneClient, QzoneError
from qqliker.config import Settings
from qqliker.snapshot import build_snapshot, write_snapshot
from qqliker.tasks import TaskReport, run_card_like, run_feed_like

ROOT = Path(__file__).resolve().parent


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def write_step_summary(reports: list[TaskReport]) -> None:
    """把结果写进 GitHub Actions 的 Job Summary，跑完在页面上直接能看。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## QQ 云端点赞执行结果", "", "| 任务 | 成功 | 跳过 | 失败 |", "| --- | --- | --- | --- |"]
    for r in reports:
        lines.append(f"| {r.name} | {r.ok} | {r.skipped} | {r.failed} |")
    lines.append("")
    for r in reports:
        lines.append(f"<details><summary>{r.name} 明细</summary>")
        lines.append("")
        if r.details:
            lines.extend(f"- {d}" for d in r.details)
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("</details>")
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def build_client(settings: Settings, dry_run: bool) -> QzoneClient:
    if not dry_run:
        settings.validate()
    return QzoneClient(
        settings.uin or "10000",
        settings.cookie or "skey=@dryrun; p_skey=dryrun",
        timeout=settings.timeout,
        dry_run=dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QQ 云端点赞机器人")
    parser.add_argument("task", choices=["check", "card-like", "feed-like", "all", "sync"])
    parser.add_argument("--times", type=int, default=None, help="每位好友点赞次数，默认 10")
    parser.add_argument("--interval", type=float, default=None, help="请求间隔秒数，默认 1.5")
    parser.add_argument("--friends", type=str, default="", help="临时覆盖好友列表，逗号分隔")
    parser.add_argument("--num", type=int, default=20, help="拉取动态条数")
    parser.add_argument("--since", type=int, default=120, help="只赞最近 N 分钟内的动态")
    parser.add_argument("--max-like", type=int, default=10, help="单次最多赞几条动态")
    parser.add_argument("--max-friends", type=int, default=0, help="单次最多处理几个好友，0 表示不限")
    parser.add_argument("--dry-run", action="store_true", help="不联网，仅打印流程")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    settings = Settings.from_env(ROOT)
    dry_run = args.dry_run or settings.dry_run
    if args.friends:
        settings.friends = [x.strip() for x in args.friends.split(",") if x.strip().isdigit()]

    try:
        client = build_client(settings, dry_run)
    except QzoneError as exc:
        log_error(str(exc))
        return 2

    times = args.times if args.times is not None else settings.like_per_friend
    interval = args.interval if args.interval is not None else settings.interval
    reports: list[TaskReport] = []

    try:
        if args.task == "check":
            nick = client.check()
            print(f"✔ Cookie 有效，当前账号: {nick} ({client.uin})")
            print(f"  g_tk = {client.gtk}")
            print(f"  好友数量 = {len(settings.friends)}")
            return 0

        if args.task in {"card-like", "all"}:
            reports.append(
                run_card_like(
                    client,
                    settings.friends,
                    times=times,
                    interval=interval,
                    max_friends=args.max_friends,
                )
            )

        if args.task == "sync":
            snap = build_snapshot(client)
            out = Path(os.environ.get("QQ_SNAPSHOT", "data/snapshot.json"))
            write_snapshot(snap, out)
            print(f"快照完成: 好友 {len(snap['friends'])} / 动态 {len(snap['feeds'])} / 赞 {len(snap['likes'])}")
            if snap["errors"]:
                print("警告:", "; ".join(snap["errors"]))
            return 0

        if args.task in {"feed-like", "all"}:
            reports.append(
                run_feed_like(
                    client,
                    num=args.num,
                    since_minutes=args.since,
                    max_like=args.max_like,
                    interval=interval,
                )
            )
    except QzoneError as exc:
        log_error(str(exc))
        return 2

    print()
    for r in reports:
        print(r.render())
        print()
    write_step_summary(reports)
    return 0


def log_error(msg: str) -> None:
    logging.error(msg)


if __name__ == "__main__":
    raise SystemExit(main())
