from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import transition
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket
from orchestrator.daemon.events import read_events

from test_routing import _git_repo


def test_pm_drafts_prd(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="加缓存")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    msg = advance_once(pool, t.id, FakeHarness(), tmp_path)
    assert msg.startswith("role:pm")
    assert load_ticket(pool, t.id).state == "p1_proposed"


def test_system_states_auto_advance(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p2_approved"
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    msg = advance_once(pool, t.id, FakeHarness(), tmp_path)
    assert load_ticket(pool, t.id).state == "p3_running"
    assert "p3_running" in msg


def test_failure_suspends(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    advance_once(pool, t.id, FakeHarness(script=["failed"]), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    assert t2.resume_state == "p1_drafting"
    assert any(e["event"] == "role_run" and e["status"] == "failed"
               for e in read_events(pool, t.id))


def test_p5_failure_creates_incident(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p5_releasing"
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(script=["failed"]), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    # 自动事故工单进池
    from pathlib import Path as P
    tickets = list((pool / "tickets").glob("*.yaml"))
    assert len(tickets) == 2
    inc = [f.stem for f in tickets if f.stem != t.id][0]
    from orchestrator.daemon.ticket import load_ticket as lt
    it = lt(pool, inc)
    assert it.type == "incident" and it.state == "p1_drafting"


def test_architect_stays_for_approval(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p2_designing"
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "p2_designing"
    assert t2.owner_role == "boss"


def test_acceptance_timeout_counts_as_failed(pool, tmp_path, monkeypatch):
    # 复检 subprocess 超时不许冒泡:按复检失败处理(搭车修复 T3)
    import subprocess as sp
    from orchestrator.daemon import runner
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "sleep 5",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)

    def boom(cmd, cwd, timeout=600):
        raise sp.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(runner, "_run_acceptance", boom)

    advance_once(pool, t.id, FakeHarness(), proj)  # harness 谎报 done,复检超时
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "pending"
    evts = [e for e in read_events(pool, t.id) if e["event"] == "task_run"]
    assert evts[-1]["verify"] == "failed"
    assert "复检超时" in evts[-1]["output"]
