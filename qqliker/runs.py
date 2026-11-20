"""执行记录：任务跑完就落一条，快照和 App 直接读它。

不走 GitHub API，避免 token 权限和匿名限流带来的空白。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
RUNS_PATH = Path("data/runs.json")
KEEP = 12


def load_runs(path: Path | None = None) -> list[dict]:
    p = path or RUNS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def record_run(
    name: str,
    ok: int = 0,
    failed: int = 0,
    skipped: int = 0,
    conclusion: str | None = None,
    note: str = "",
    path: Path | None = None,
) -> dict:
    """写入一条执行记录，最新的排在最前面。"""
    p = path or RUNS_PATH
    if conclusion is None:
        conclusion = "failure" if failed and ok == 0 else "success"

    entry = {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "created_at": datetime.now(CST).isoformat(timespec="seconds"),
        "ok": ok,
        "failed": failed,
        "skipped": skipped,
        "note": note,
    }

    runs = [r for r in load_runs(p) if isinstance(r, dict)]
    runs.insert(0, entry)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(runs[:KEEP], ensure_ascii=False, indent=1), encoding="utf-8")
    return entry
