import pytest
import yaml

from orchestrator.daemon.statemachine import (
    APPROVALS, IllegalTransition, resume, suspend, transition,
)
from orchestrator.daemon.ticket import Ticket, new_ticket
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


def test_suspended_can_close_by_boss(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    suspend(pool, t, actor="system", reason="熔断用尽")
    transition(pool, t, "closed", actor="boss")
    assert t.state == "closed"


def test_suspended_close_requires_boss(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    suspend(pool, t, actor="system", reason="熔断用尽")
    with pytest.raises(IllegalTransition):
        transition(pool, t, "closed", actor="pm")  # 关闭挂起工单是老板特权


# ---- D2:P1 重做边(p1_proposed → p1_drafting,boss)+ p1_round 轮次追踪 ----

def _ticket_at_p1_proposed(pool):
    """走正常审批链到 p1_proposed:pm 提案 → boss 放行 → pm 交 PRD。"""
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    transition(pool, t, "p1_proposed", actor="pm")
    return t


def test_p1_redo_edge_boss_sends_back(pool):
    t = _ticket_at_p1_proposed(pool)
    transition(pool, t, "p1_drafting", actor="boss")
    assert t.state == "p1_drafting"
    assert t.p1_round == 1
    ev = read_events(pool, t.id)[-1]
    assert ev["event"] == "state_changed"
    assert ev["frm"] == "p1_proposed" and ev["to"] == "p1_drafting"
    assert ev["round"] == 1  # 轮次随事件留痕


def test_p1_redo_round_accumulates(pool):
    t = _ticket_at_p1_proposed(pool)
    transition(pool, t, "p1_drafting", actor="boss")   # 第 1 轮驳回
    transition(pool, t, "p1_proposed", actor="pm")     # PM 重交
    transition(pool, t, "p1_drafting", actor="boss")   # 第 2 轮驳回
    assert t.p1_round == 2
    rounds = [e["round"] for e in read_events(pool, t.id)
              if e["event"] == "state_changed" and "round" in e]
    assert rounds == [1, 2]  # 不重置,历史轮次经事件流可追


def test_p1_redo_requires_boss(pool):
    t = _ticket_at_p1_proposed(pool)
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p1_drafting", actor="pm")  # 驳回回炉是老板特权
    assert t.state == "p1_proposed" and t.p1_round == 0  # 失败迁移不留痕


def test_old_ticket_yaml_loads_p1_round_zero(tmp_path):
    """兼容:既有工单 yaml 无 p1_round 字段,load 兜底 0,平滑迁移。"""
    legacy = {"id": "T-2026-0828-901", "type": "feature", "project": "p",
              "state": "p1_proposed", "owner_role": "pm", "summary": "legacy"}
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump(legacy), encoding="utf-8")
    assert Ticket.load(path).p1_round == 0
