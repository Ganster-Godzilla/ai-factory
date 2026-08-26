"""工单状态机。迁移即事件;审批门禁见 spec 第 2 节。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.daemon.events import append_event
from orchestrator.daemon.ticket import Ticket, save_ticket

TRANSITIONS = {
    "draft":         {"p0_proposed": {"pm"}, "closed": {"boss"}},
    "p0_proposed":   {"p1_drafting": {"boss"}, "closed": {"boss"}},
    "p1_drafting":   {"p1_proposed": {"pm"}, "suspended": {"*"}},
    "p1_proposed":   {"p2_designing": {"boss"}, "closed": {"boss"}},
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


class IllegalTransition(Exception):
    pass


def transition(pool: Path, ticket: Ticket, to_state: str, actor: str, **ev) -> Ticket:
    allowed = TRANSITIONS.get(ticket.state, {}).get(to_state)
    if allowed is None:
        raise IllegalTransition(f"{ticket.state} → {to_state} 不在迁移表")
    if "*" not in allowed and actor not in allowed:
        raise IllegalTransition(f"{ticket.state} → {to_state} 不允许 actor={actor}")
    frm = ticket.state
    ticket.state = to_state
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "state_changed", frm=frm, to=to_state, **ev)
    return ticket


def suspend(pool: Path, ticket: Ticket, actor: str, reason: str) -> Ticket:
    if ticket.state in {"done", "closed", "suspended"}:
        raise IllegalTransition(f"{ticket.state} 不可挂起")
    ticket.resume_state = ticket.state
    ticket.state = "suspended"
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "suspended",
                 resume_state=ticket.resume_state, reason=reason)
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
