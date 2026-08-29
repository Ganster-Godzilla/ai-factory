"""工单状态机。迁移即事件;审批门禁见 spec 第 2 节。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.daemon.events import append_event
from orchestrator.daemon.ticket import Ticket, save_ticket

TRANSITIONS = {
    "draft":         {"p0_proposed": {"pm", "boss"}, "closed": {"boss"}},
    "p0_proposed":   {"p1_drafting": {"boss"}, "closed": {"boss"}},
    "p1_drafting":   {"p1_proposed": {"pm"}, "suspended": {"*"}},
    "p1_proposed":   {"p2_designing": {"boss"}, "p1_drafting": {"boss"}, "closed": {"boss"}},
    "p2_designing":  {"p2_approved": {"boss"}, "p1_drafting": {"boss"}, "suspended": {"*"}},
    "p2_approved":   {"p3_queued": {"system"}},
    "p3_queued":     {"p3_running": {"system"}},
    "p3_running":    {"p4_verifying": {"system"}, "suspended": {"*"}},
    "p4_verifying":  {"p5_ready": {"qa"}, "p3_running": {"qa"}, "suspended": {"*"}},
    "p5_ready":      {"p5_releasing": {"boss"}, "suspended": {"*"}},
    "p5_releasing":  {"monitoring": {"release"}, "suspended": {"*"}},
    "monitoring":    {"done": {"sre"}, "suspended": {"*"}},
    "suspended":     {"closed": {"boss"}},
    "done":          {},
    "closed":        {},
}

APPROVALS = {
    "p0_proposed": "p1_drafting",
    "p1_proposed": "p2_designing",
    "p2_designing": "p2_approved",
    "p5_ready": "p5_releasing",
}

# suspend 事件 reason_code 词汇表(spec §5.2/§5.3);可选,None 表示无对应枚举
SUSPEND_REASON_CODES = {
    "budget_cap", "daily_cap", "circuit_exhausted", "consult_exhausted",
    "quota_exceeded", "deadlock", "load_failed", "release_failed",
    "verify_failed", "manual",
    "artifact_missing",   # T-2026-0829-001:门禁产物缺失/要素不全挂起
}

# P1 重做边(D2):PRD 驳回回炉,actor 限 boss。轮次计数在 transition 内统一记,
# CLI/dashboard 等任何入口都经此走,不会漏计
P1_REDO_EDGE = ("p1_proposed", "p1_drafting")


class IllegalTransition(Exception):
    pass


def _enforce_gate(project_dir, ticket: Ticket, to_state: str) -> None:
    """产物门禁(T-2026-0829-001 M4):门禁边+新单强制校验。
    project_dir 缺失=开发错误;check_gate 非空=IllegalTransition 含全部 FAIL 行。
    注:测试默认经 conftest 旁路本函数(隔离既有用例),真闸门见 test_gate_enforcement。"""
    from orchestrator.daemon.artifacts import manifest_for_edge
    from orchestrator.daemon.gates import check_gate, gate_required
    if manifest_for_edge(ticket.state, to_state) is None:
        return
    if not gate_required(ticket):
        return
    if project_dir is None:
        raise IllegalTransition(
            f"门禁边({ticket.state}→{to_state})需要 project_dir(开发错误)")
    fails = check_gate(project_dir, ticket, to_state)
    if fails:
        raise IllegalTransition("门禁校验未过:\n" + "\n".join(fails))


def transition(pool: Path, ticket: Ticket, to_state: str, actor: str,
               project_dir: Path | None = None, **ev) -> Ticket:
    allowed = TRANSITIONS.get(ticket.state, {}).get(to_state)
    if allowed is None:
        raise IllegalTransition(f"{ticket.state} → {to_state} 不在迁移表")
    if "*" not in allowed and actor not in allowed:
        raise IllegalTransition(f"{ticket.state} → {to_state} 不允许 actor={actor}")
    _enforce_gate(project_dir, ticket, to_state)
    frm = ticket.state
    ticket.state = to_state
    if (frm, to_state) == P1_REDO_EDGE:
        # 轮次追踪(D2):+1 不重置,历史轮次经事件流可追;
        # getattr 兜底:内存中的旧工单对象可能没有 p1_round 字段
        ticket.p1_round = getattr(ticket, "p1_round", 0) + 1
        ev.setdefault("round", ticket.p1_round)
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "state_changed", frm=frm, to=to_state, **ev)
    return ticket


def suspend(pool: Path, ticket: Ticket, actor: str, reason: str,
            reason_code: str | None = None) -> Ticket:
    if ticket.state in {"done", "closed", "suspended"}:
        raise IllegalTransition(f"{ticket.state} 不可挂起")
    ticket.resume_state = ticket.state
    ticket.state = "suspended"
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "suspended",
                 resume_state=ticket.resume_state, reason=reason,
                 reason_code=reason_code)
    return ticket


def resume(pool: Path, ticket: Ticket, actor: str) -> Ticket:
    if ticket.state != "suspended" or not ticket.resume_state:
        raise IllegalTransition("非挂起状态,无法恢复")
    target = ticket.resume_state
    ticket.state = target
    ticket.resume_state = None
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "resumed", to=target)
    return ticket
