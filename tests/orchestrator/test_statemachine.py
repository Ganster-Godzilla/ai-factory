import pytest

from orchestrator.daemon.statemachine import (
    APPROVALS, IllegalTransition, resume, suspend, transition,
)
from orchestrator.daemon.ticket import new_ticket
from orchestrator.daemon.events import read_events


def test_happy_path_boss_approves_p0(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, APPROVALS["p0_proposed"], actor="boss")
    assert t.state == "p1_drafting"
    events = read_events(pool, t.id)
    assert events[-1]["event"] == "state_changed"
    assert events[-1]["to"] == "p1_drafting"


def test_illegal_transition_rejected(pool):
    t = new_ticket(pool, project="p", summary="x")
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p3_running", actor="pm")


def test_wrong_actor_rejected(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p1_drafting", actor="pm")  # 审批是老板特权


def test_suspend_resume(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    suspend(pool, t, actor="system", reason="熔断用尽")
    assert t.state == "suspended"
    assert t.resume_state == "p0_proposed"
    resume(pool, t, actor="boss")
    assert t.state == "p0_proposed"
    assert t.resume_state is None


def test_done_is_terminal(pool):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "done"
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p0_proposed", actor="boss")
