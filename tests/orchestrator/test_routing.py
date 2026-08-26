from orchestrator.adapters import get_adapter
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
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
    # worktree 名按工单命名空间隔离,跨工单不串
    assert t.id in str(h.received[0].workdir)


def _write_tasks_yaml(proj, tid, body):
    d = proj / "docs" / "specs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tid}-tasks.yaml").write_text(body, encoding="utf-8", newline="\n")


def test_p3_lazy_loads_tasks_yaml(pool, tmp_path):
    # 架构师产物 docs/specs/<tid>-tasks.yaml 存在时,p3 首次推进应装载进 ticket.tasks
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    save_ticket(pool, t)  # tasks 为空
    _write_tasks_yaml(proj, t.id, (
        "- id: task-1\n  title: a\n  acceptance_cmd: 'true'\n  depends_on: []\n"
        "- id: task-2\n  title: b\n  acceptance_cmd: 'true'\n  depends_on: [task-1]\n"
    ))
    h = FakeHarness()
    advance_once(pool, t.id, h, proj)
    t2 = load_ticket(pool, t.id)
    assert len(t2.tasks) == 2
    assert t2.tasks[0]["status"] == "done"      # task-1 被派发且完成
    assert t2.tasks[1]["status"] == "pending"   # task-2 依赖未满足
    assert t2.state == "p3_running"
    assert "task-1" in str(h.received[0].workdir)
    assert t.id in str(h.received[0].workdir)


def test_p3_bad_tasks_yaml_suspends(pool, tmp_path):
    # 畸形 YAML 不得裸抛:工单应挂起,reason 说明装载失败
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    save_ticket(pool, t)
    _write_tasks_yaml(proj, t.id, "{{{[not yaml")
    advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    assert t2.resume_state == "p3_running"
    assert any(e["event"] == "suspended" and "装载失败" in e["reason"]
               for e in read_events(pool, t.id))


def test_p3_no_tasks_yaml_keeps_auto_p4(pool, tmp_path):
    # 无 tasks.yaml 时维持现状:空 tasks → auto p4,不派发任何任务
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    save_ticket(pool, t)
    h = FakeHarness()
    msg = advance_once(pool, t.id, h, proj)
    assert msg == "auto: p4_verifying"
    assert load_ticket(pool, t.id).state == "p4_verifying"
    assert h.received == []


def test_failed_task_run_event_carries_output(pool, tmp_path):
    # 失败任务的 task_run 事件必须带 output,排查不靠猜
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": "task-1", "title": "a", "acceptance_cmd": "true", "depends_on": [],
         "status": "pending", "attempts": 0},
    ]
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(script=["failed"]), proj)
    ev = [e for e in read_events(pool, t.id) if e["event"] == "task_run"]
    assert ev and ev[-1]["status"] == "failed"
    assert "output" in ev[-1] and "fake" in ev[-1]["output"]
