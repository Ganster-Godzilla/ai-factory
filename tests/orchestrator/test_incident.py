"""T-2026-0901-021 D1:create_incident 去重三态。"""

from orchestrator.daemon.events import read_events
from orchestrator.daemon.incident import create_incident, find_open_incident
from orchestrator.daemon.statemachine import suspend, transition
from orchestrator.daemon.ticket import load_ticket, new_ticket


def _origin(pool):
    return new_ticket(pool, "ai-factory", "原单", created_by="human")


def test_first_failure_creates(pool):
    origin = _origin(pool)
    inc = create_incident(pool, origin, f"发布失败: {origin.id}")
    assert inc.type == "incident" and inc.related_ticket == origin.id
    assert any(e["event"] == "incident_created"
               for e in read_events(pool, origin.id))


def test_repeat_failure_reuses_no_new_ticket(pool):
    origin = _origin(pool)
    first = create_incident(pool, origin, f"发布失败: {origin.id}")
    before = len(list((pool / "tickets").glob("T-*.yaml")))
    second = create_incident(pool, origin, f"部署/冒烟失败:{origin.id}")
    assert second.id == first.id                      # 复用同一张
    assert len(list((pool / "tickets").glob("T-*.yaml"))) == before   # 池子不增
    evts = read_events(pool, first.id)
    assert any(e["event"] == "incident_evidence" for e in evts)
    assert any(e["event"] == "incident_reused" and e.get("incident") == first.id
               for e in read_events(pool, origin.id))


def test_closed_incident_allows_new(pool):
    origin = _origin(pool)
    first = create_incident(pool, origin, "f")
    # incident 单起步 p1_drafting;走 suspended → closed
    t = load_ticket(pool, first.id)
    suspend(pool, t, actor="boss", reason="处置完", reason_code="manual")
    transition(pool, t, "closed", actor="boss")
    second = create_incident(pool, origin, "f")
    assert second.id != first.id                      # 已关闭 → 允许新建
    assert find_open_incident(pool, origin.id).id == second.id


def test_suspended_incident_still_reused(pool):
    origin = _origin(pool)
    first = create_incident(pool, origin, "f")
    t = load_ticket(pool, first.id)
    suspend(pool, t, actor="boss", reason="挂着", reason_code="manual")
    second = create_incident(pool, origin, "f")
    assert second.id == first.id                      # suspended 也算未关闭
