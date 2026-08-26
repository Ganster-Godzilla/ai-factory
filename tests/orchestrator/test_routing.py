from orchestrator.adapters import get_adapter
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.runner import ROLE_ROUTING, advance_once
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket
import subprocess


def _git_repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=r, check=True, capture_output=True)
    return r


def test_routing():
    assert ROLE_ROUTING["dev"] == "dsh"
    assert ROLE_ROUTING["pm"] == "claude_code"
    assert isinstance(get_adapter("fake"), FakeHarness)


def test_p3_dispatches_ready_tasks(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": "task-1", "title": "a", "acceptance_cmd": "true", "depends_on": [],
         "status": "pending", "attempts": 0},
        {"id": "task-2", "title": "b", "acceptance_cmd": "true", "depends_on": ["task-1"],
         "status": "pending", "attempts": 0},
    ]
    save_ticket(pool, t)
    h = FakeHarness()
    msg = advance_once(pool, t.id, h, proj)
    t2 = load_ticket(pool, t.id)
    # 一次 advance 只派一个 ready 任务;task-2 依赖未满足
    assert t2.tasks[0]["status"] == "done"
    assert t2.tasks[1]["status"] == "pending"
    assert t2.state == "p3_running"
    # 任务包发到了该任务的 worktree
    assert "orc-task-1" in str(h.received[0].workdir) or "task-1" in str(h.received[0].workdir)
