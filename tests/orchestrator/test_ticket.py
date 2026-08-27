import pytest
from orchestrator.daemon.ticket import Ticket, new_ticket, load_ticket, save_ticket


def test_new_ticket_defaults(pool):
    t = new_ticket(pool, project="quant-lab", summary="补测试", created_by="probe")
    assert t.state == "draft"
    assert t.owner_role == "pm"
    assert t.type == "feature"
    assert t.priority == "normal"
    assert t.budget == {"token_cap": 500000, "token_cap_cny": 10.0}
    assert t.id.startswith("T-")
    assert load_ticket(pool, t.id).summary == "补测试"


def test_incident_ticket_fast_lane(pool):
    t = new_ticket(pool, project="p", summary="发布失败", created_by="system", type="incident")
    assert t.state == "p1_drafting"
    assert t.priority == "high"
    assert t.type == "incident"


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


def test_saved_yaml_is_lf_only(pool):
    t = new_ticket(pool, project="quant-lab", summary="换行口径")
    save_ticket(pool, t)
    raw = (pool / "tickets" / f"{t.id}.yaml").read_bytes()
    assert b"\r" not in raw


def test_concurrent_new_ticket_unique_ids(pool):
    import threading
    ids = []
    def mk(i):
        ids.append(new_ticket(pool, project="p", summary=f"s{i}").id)
    threads = [threading.Thread(target=mk, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(ids)) == 8


def test_load_ticket_rejects_traversal_id(pool):
    # %5C 反斜杠路径遍历面:id 不匹配 ID_RE 直接抛 ValueError,不拼路径
    with pytest.raises(ValueError):
        load_ticket(pool, "..\\..\\evil")
