"""开发角色的工位:每任务一个 git worktree,崩了最多损失一个。"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(project: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=project, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def ensure_worktree(project: Path, name: str, base: str = "main") -> Path:
    wt = project / ".orc-worktrees" / name
    if wt.exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(project, "worktree", "add", str(wt), "-b", f"orc/{name}", base)
    return wt


def list_worktrees(project: Path) -> list[str]:
    root = project / ".orc-worktrees"
    if not root.exists():
        return []
    return [p.name for p in root.iterdir() if p.is_dir()]


def recycle_worktree(project: Path, name: str) -> None:
    _git(project, "worktree", "remove", "--force", str(project / ".orc-worktrees" / name))
    _git(project, "branch", "-D", f"orc/{name}")
