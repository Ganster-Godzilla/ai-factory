import subprocess
from pathlib import Path
import pytest
from orchestrator.daemon.worktree import ensure_worktree, list_worktrees, recycle_worktree


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "README.md").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=r, check=True, capture_output=True)
    return r


def test_ensure_and_recycle(repo):
    wt = ensure_worktree(repo, "task-1")
    assert wt.exists()
    assert (wt / "README.md").exists()
    assert "task-1" in list_worktrees(repo)
    # 复用:不报错,路径相同
    assert ensure_worktree(repo, "task-1") == wt
    recycle_worktree(repo, "task-1")
    assert "task-1" not in list_worktrees(repo)


def test_ensure_writes_orc_base(repo):
    # R7:创建 worktree 时把当前 HEAD 落盘为 .orc-base,供越界检查的 git diff 使用
    wt = ensure_worktree(repo, "task-base")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True,
                          text=True, check=True).stdout.strip()
    base_file = wt / ".orc-base"
    assert base_file.exists()
    assert base_file.read_text(encoding="utf-8").strip() == head
    # 复用既有 worktree:不重写 base(旧落盘值保持,创建动作只发生一次)
    base_file.write_text("stale", encoding="utf-8")
    assert ensure_worktree(repo, "task-base") == wt
    assert base_file.read_text(encoding="utf-8") == "stale"
    recycle_worktree(repo, "task-base")
    assert not base_file.exists()
