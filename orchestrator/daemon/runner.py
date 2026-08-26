"""执行器:对工单当前状态推进一步。M1 形态:同步单步;常驻循环在 M3+。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, TaskPacket
from orchestrator.daemon.events import append_event
from orchestrator.daemon.slicer import make_packet, ready_tasks
from orchestrator.daemon.statemachine import suspend, transition
from orchestrator.daemon.ticket import load_ticket, save_ticket
from orchestrator.daemon.worktree import ensure_worktree

ROLE_ROUTING = {
    "pm": "claude_code", "architect": "claude_code", "test_designer": "claude_code",
    "qa_vision": "claude_code", "dev": "dsh", "qa": "dsh",
    "release": "dsh", "sre": "dsh",
}

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


def run_dev_tasks(pool: Path, ticket, adapter: HarnessAdapter,
                  project_dir: Path) -> str:
    ready = ready_tasks(ticket.tasks)
    if not ready:
        if all(t["status"] == "done" for t in ticket.tasks):
            transition(pool, ticket, "p4_verifying", actor="system")
            return "auto: p4_verifying"
        return "idle: p3_running(no ready tasks)"
    task = ready[0]
    wt = ensure_worktree(project_dir, task["id"])
    packet = make_packet(task, ticket, wt, design_excerpt="")
    result = adapter.run(packet)
    task["attempts"] += 1
    append_event(pool, ticket.id, "dev", "task_run", task=task["id"],
                 attempt=task["attempts"], status=result.status,
                 tokens=result.tokens, cost_cny=result.cost_cny)
    if result.status == "done":
        task["status"] = "done"
        save_ticket(pool, ticket)
    else:
        save_ticket(pool, ticket)  # attempts 已记;熔断阶梯 M3 接管
        suspend(pool, ticket, actor="system",
                reason=f"任务 {task['id']} 第 {task['attempts']} 次失败")
    return f"task:{task['id']}:{result.status}"


def _role_prompt(role: str) -> str:
    path = Path(__file__).parent.parent / "roles" / "prompts" / f"{role}.md"
    return path.read_text(encoding="utf-8")


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

    if t.state == "p3_running":
        return run_dev_tasks(pool, t, adapter, project_dir)

    packet = TaskPacket(
        role=role,
        prompt=_role_prompt(role) + f"\n[{role}] 工单 {t.id}: {t.summary}",
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
