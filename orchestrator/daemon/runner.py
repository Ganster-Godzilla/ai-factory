"""执行器:对工单当前状态推进一步。M1 形态:同步单步;常驻循环在 M3+。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, TaskPacket
from orchestrator.daemon.events import append_event
from orchestrator.daemon.statemachine import suspend, transition
from orchestrator.daemon.ticket import load_ticket, save_ticket

WORK_STATES = {
    "p1_drafting": "pm",
    "p2_designing": "architect",
    "p3_running": "dev",
    "p4_verifying": "qa",
    "p5_releasing": "release",
    "monitoring": "sre",
}

SUCCESS_NEXT = {
    "p1_drafting": "p1_proposed",
    "p3_running": "p4_verifying",
    "p4_verifying": "p5_ready",
    "p5_releasing": "monitoring",
    "monitoring": "done",
}

SYSTEM_NEXT = {"p2_approved": "p3_queued", "p3_queued": "p3_running"}


def advance_once(pool: Path, ticket_id: str, adapter: HarnessAdapter,
                 project_dir: Path) -> str:
    t = load_ticket(pool, ticket_id)

    if t.state in SYSTEM_NEXT:
        while t.state in SYSTEM_NEXT:
            transition(pool, t, SYSTEM_NEXT[t.state], actor="system")
        return f"auto: {t.state}"

    role = WORK_STATES.get(t.state)
    if role is None:
        return f"idle: {t.state}"

    packet = TaskPacket(
        role=role,
        prompt=f"[{role}] 工单 {t.id}: {t.summary}",
        workdir=project_dir,
        budget=t.budget,
    )
    result = adapter.run(packet)
    append_event(pool, t.id, role, "role_run",
                 status=result.status, tokens=result.tokens,
                 cost_cny=result.cost_cny, output=result.output[:500])

    if result.status == "done":
        if t.state == "p2_designing":
            t.owner_role = "boss"
            save_ticket(pool, t)
        else:
            transition(pool, t, SUCCESS_NEXT[t.state], actor="system" if t.state == "p3_running" else role)
    else:
        suspend(pool, t, actor="system", reason=f"{role} 执行失败: {result.status}")
    return f"role:{role}:{result.status}"
