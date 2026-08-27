"""执行器:对工单当前状态推进一步。M1 形态:同步单步;常驻循环在 M3+。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from orchestrator.adapters import get_adapter
from orchestrator.adapters.base import HarnessAdapter, TaskPacket
from orchestrator.daemon.circuitbreaker import (
    MAX_RETRY, consult_packet, next_action, retry_prompt,
)
from orchestrator.daemon.events import append_event
from orchestrator.daemon.gateway import k3_effective_week_tokens
from orchestrator.daemon.ledger import append_ledger
from orchestrator.daemon.slicer import load_task_list, make_packet, ready_tasks
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

ADAPTER_RESOURCE = {"claude_code": ("k3", "tokens"), "dsh": ("deepseek", "cny")}


def _record_cost(pool: Path, ticket, adapter: HarnessAdapter, result, role: str) -> None:
    res = ADAPTER_RESOURCE.get(adapter.name)
    if not res:
        return
    resource, unit = res
    amount = sum(result.tokens.values()) if unit == "tokens" else result.cost_cny
    if amount:
        append_ledger(pool, resource, amount, unit, ticket.id, role, adapter.name)


def _run_acceptance(cmd: str, cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    if os.name == "nt":
        # Windows 下 shell=True+executable 会按 cmd /c 拼装(bash 不认 /c),
        # 且 CreateProcess 不对 executable 搜 PATH;改用 argv 直调 git-bash
        return subprocess.run([shutil.which("bash") or "bash", "-c", cmd],
                              cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    return subprocess.run(cmd, shell=True, executable="bash",
                          cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def run_dev_tasks(pool: Path, ticket, adapter: HarnessAdapter,
                  project_dir: Path, cfg: dict | None = None,
                  consult_adapter: HarnessAdapter | None = None) -> str:
    if not ticket.tasks:
        # 架构师产物 lazy-load:docs/specs/<ticket.id>-tasks.yaml → ticket.tasks
        spec = project_dir / "docs" / "specs" / f"{ticket.id}-tasks.yaml"
        if spec.exists():
            try:
                ticket.tasks = load_task_list(spec)
            except Exception as e:
                suspend(pool, ticket, "system", reason=f"任务清单装载失败: {e}")
                return f"suspended: 任务清单装载失败: {e}"
            save_ticket(pool, ticket)
    ready = ready_tasks(ticket.tasks)
    if not ready:
        if all(t["status"] == "done" for t in ticket.tasks):
            transition(pool, ticket, "p4_verifying", actor="system")
            return "auto: p4_verifying"
        suspend(pool, ticket, actor="system",
                reason="无可派发任务且未完成:依赖死锁或依赖缺失")
        return "suspend: 依赖死锁"
    task = ready[0]
    wt = ensure_worktree(project_dir, f"{ticket.id}-{task['id']}")
    packet = make_packet(task, ticket, wt, design_excerpt="")
    if task["attempts"] > 0:
        packet.prompt = retry_prompt(task, packet.prompt, task.get("last_error", ""))
    result = adapter.run(packet)
    task["attempts"] += 1
    verify = None
    if result.status == "done" and task.get("acceptance_cmd"):
        try:
            r = _run_acceptance(task["acceptance_cmd"], wt)
        except subprocess.TimeoutExpired:
            verify = "failed"
            result.status = "failed"
            result.output += "\n[acceptance 复检超时]"
        else:
            verify = "passed" if r.returncode == 0 else "failed"
            if r.returncode != 0:
                result.status = "failed"
                result.output += f"\n[acceptance 复检失败 exit={r.returncode}]\n{(r.stdout + r.stderr)[-1000:]}"
    append_event(pool, ticket.id, "dev", "task_run", task=task["id"],
                 attempt=task["attempts"], status=result.status,
                 tokens=result.tokens, cost_cny=result.cost_cny,
                 output=result.output[:500], verify=verify)
    if result.status == "done":
        task["status"] = "done"
        save_ticket(pool, ticket)
        if cfg:
            _record_cost(pool, ticket, adapter, result, "dev")
        return f"task:{task['id']}:done"

    task["last_error"] = result.output[:800]
    save_ticket(pool, ticket)  # attempts 已记
    action = next_action(task)
    if action == "retry":
        return f"retry:{task['id']}:{task['attempts']}"
    if action == "consult":
        if (cfg and ticket.type != "incident"
                and k3_effective_week_tokens(pool, cfg) > cfg["budgets"]["k3_week_token_budget"]):
            suspend(pool, ticket, actor="system",
                    reason="k3 配额超线,会诊通道关闭,任务挂起")
            return "suspend: k3 配额超线"
        ca = consult_adapter or get_adapter("claude_code")
        cp = consult_packet(task, ticket, result.output, wt)
        cr = ca.run(cp)
        if cr.status == "done":
            task["consulted"] = True
            task["attempts"] = MAX_RETRY - 1   # 会诊后只再给 1 次
        # 会诊失败不置 consulted、不重置 attempts:会诊机会保留,事件与台账如实记
        task["consult_note"] = cr.output[:1000]
        append_event(pool, ticket.id, "architect", "consult",
                     task=task["id"], status=cr.status, output=cr.output[:500])
        save_ticket(pool, ticket)
        if cfg:
            _record_cost(pool, ticket, ca, cr, "architect")
        return f"consult:{task['id']}:{cr.status}"
    suspend(pool, ticket, actor="system",
            reason=f"任务 {task['id']} 会诊后仍失败")
    return f"suspend:{task['id']}"


def _role_prompt(role: str) -> str:
    path = Path(__file__).parent.parent / "roles" / "prompts" / f"{role}.md"
    return path.read_text(encoding="utf-8")


def advance_once(pool: Path, ticket_id: str, adapter: HarnessAdapter,
                 project_dir: Path, cfg: dict | None = None,
                 consult_adapter: HarnessAdapter | None = None) -> str:
    t = load_ticket(pool, ticket_id)

    if t.state in SYSTEM_NEXT:
        while t.state in SYSTEM_NEXT:
            transition(pool, t, SYSTEM_NEXT[t.state], actor="system")
        return f"auto: {t.state}"

    role = WORK_STATES.get(t.state)
    if role is None:
        return f"idle: {t.state}"

    if t.state == "p3_running":
        return run_dev_tasks(pool, t, adapter, project_dir,
                             cfg=cfg, consult_adapter=consult_adapter)

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
    if cfg:
        # 成功失败都入账:k3 烧掉就是烧掉了,配额闸水位不能漏记
        _record_cost(pool, t, adapter, result, role)

    if result.status == "done":
        if t.state == "p2_designing":
            t.owner_role = "boss"
            save_ticket(pool, t)
        else:
            transition(pool, t, SUCCESS_NEXT[t.state], actor="system" if t.state == "p3_running" else role)
    else:
        if t.state == "p5_releasing":
            suspend(pool, t, actor="system", reason=f"发布失败: {result.status}")
            from orchestrator.daemon.ticket import new_ticket as _nt
            _nt(pool, t.project, f"发布失败: {t.id} {t.summary}",
                created_by="system", type="incident")
        else:
            suspend(pool, t, actor="system", reason=f"{role} 执行失败: {result.status}")
    return f"role:{role}:{result.status}"
