"""运行配置：全部来自环境变量，方便在 GitHub Actions / Cloudflare 里注入。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_INTERVAL = 1.5  # 每次点赞之间的间隔（秒）


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_control_file(path: Path) -> list[str]:
    """读取 App 控制面板写入的开关配置。"""
    import json

    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(x) for x in (data.get("enabled") or []) if str(x).isdigit()]
    except Exception:
        return []


def load_friends_file(path: Path) -> list[str]:
    """从文本文件读好友 QQ 号，每行一个，# 开头为注释。"""
    if not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line.isdigit():
            out.append(line)
    return out


@dataclass
class Settings:
    uin: str = ""
    cookie: str = ""
    friends: list[str] = field(default_factory=list)
    like_per_friend: int = 10
    interval: float = DEFAULT_INTERVAL
    dry_run: bool = False
    timeout: int = 20

    @classmethod
    def from_env(cls, root: str | Path = ".") -> "Settings":
        root = Path(root)
        # 优先级：前端控制面板 > 仓库变量 > 文本文件
        friends = load_control_file(root / "config" / "control.json")
        if not friends:
            raw_friends = os.environ.get("QQ_FRIENDS", "")
            friends = [x.strip() for x in raw_friends.replace("，", ",").split(",") if x.strip().isdigit()]
        if not friends:
            friends = load_friends_file(root / "config" / "friends.txt")
        return cls(
            uin=os.environ.get("QQ_UIN", "").strip(),
            cookie=os.environ.get("QQ_COOKIE", "").strip(),
            friends=friends,
            like_per_friend=_env_int("QQ_LIKE_TIMES", 10),
            interval=_env_float("QQ_LIKE_INTERVAL", DEFAULT_INTERVAL),
            dry_run=os.environ.get("QQ_DRY_RUN", "").lower() in {"1", "true", "yes"},
            timeout=_env_int("QQ_TIMEOUT", 20),
        )

    def validate(self) -> None:
        missing = []
        if not self.uin:
            missing.append("QQ_UIN")
        if not self.cookie:
            missing.append("QQ_COOKIE")
        if missing:
            raise SystemExit(f"缺少必填环境变量: {', '.join(missing)}")
        if not self.uin.isdigit():
            raise SystemExit(f"QQ_UIN 必须是纯数字 QQ 号，当前为: {self.uin!r}")
