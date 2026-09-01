"""incident 自动建单去重(T-2026-0901-021)。

发布/冒烟失败自动建 incident 单必须收口到本模块:原单已有未关闭的
incident(非 done/closed)时**复用**而不新建——否则重试循环一次失败一张单
(2026-09-01 T-2026-0901-007 实证:1.5h 雪崩 9+ 张重复单)。

复用语义:不新建、不改 summary(保留首创信息);证据写双方事件流
(incident 侧 incident_evidence,原单侧 incident_reused),双向可查不变。
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.daemon.events import append_event
from orchestrator.daemon.ticket import Ticket, new_ticket

OPEN_STATES_EXCLUDED = {"done", "closed"}


def find_open_incident(pool: Path, origin_id: str) -> Ticket | None:
    """原单的未关闭 incident 单;多张时取 id 最大(最新)一张。"""
    cands = []
    for p in (pool / "tickets").glob("T-*.yaml"):
        try:
            t = Ticket.load(p)
        except Exception:  # noqa: BLE001 — 扫描容错,坏单不挡去重判断
            continue
        if t.type == "incident" and t.related_ticket == origin_id \
                and t.state not in OPEN_STATES_EXCLUDED:
            cands.append(t)
    return max(cands, key=lambda t: t.id) if cands else None


def create_incident(pool: Path, ticket, summary: str) -> Ticket:
    """失败自动建单(去重):有未关闭 incident → 复用;否则新建并双向留痕。"""
    inc = find_open_incident(pool, ticket.id)
    if inc is not None:
        append_event(pool, inc.id, "system", "incident_evidence",
                     note=f"复用:原单 {ticket.id} 再次失败,证据见原单事件流")
        append_event(pool, ticket.id, "system", "incident_reused", incident=inc.id)
        return inc
    inc = new_ticket(pool, ticket.project, summary,
                     created_by="system", type="incident",
                     related_ticket=ticket.id)
    append_event(pool, ticket.id, "system", "incident_created", incident=inc.id)
    return inc
