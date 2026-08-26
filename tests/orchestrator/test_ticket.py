import pytest
from orchestrator.daemon.ticket import Ticket, new_ticket, load_ticket, save_ticket


def test_new_ticket_defaults(pool):
    t = new_ticket(pool, project="quant-lab", summary="补测试", created_by="probe")
    assert t.state == "draft"
    assert t.owner_role == "pm"
    assert t.type == "feature"
    assert t.priority == "normal"
    assert t.budget == {"token_cap": 500000}
    assert t.id.startswith("T-")
    assert load_ticket(pool, t.id).summary == "补测试"


def test_validate_catches_bad(pool):
    t = new_ticket(pool, project="quant-lab", summary="x")
    t.state = "not_a_state"
    problems = t.validate()
    assert any("state" in p for p in problems)


def test_save_and_load_roundtrip(pool):
    t = new_ticket(pool, project="quant-lab", summary="x")
    t.tasks = [{"id": "task-1", "status": "pending", "depends_on": []}]
    save_ticket(pool, t)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["id"] == "task-1"
    assert t2.resume_state is None


def test_id_increments(pool):
    a = new_ticket(pool, project="p", summary="a")
    b = new_ticket(pool, project="p", summary="b")
    assert a.id != b.id
