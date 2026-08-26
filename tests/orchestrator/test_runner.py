from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import transition
from orchestrator.daemon.ticket import load_ticket, new_ticket
from orchestrator.daemon.events import read_events


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


def test_architect_stays_for_approval(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p2_designing"
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "p2_designing"
    assert t2.owner_role == "boss"
