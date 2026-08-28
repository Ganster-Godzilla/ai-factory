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
from orchestrator.daemon.ledger import append_ledger, ds_daily_exceeded, ds_ticket_cost
from orchestrator.daemon.slicer import load_task_list, make_packet, ready_tasks, scope_violations
from orchestrator.daemon.statemachine import suspend, transition
from orchestrator.daemon.ticket import load_ticket, save_ticket
from orchestrator.daemon.worktree import ensure_worktree

ROLE_ROUTING = {
    "pm": "claude_code", "architect": "claude_code", "test_designer": "claude_code",
    "qa_vision": "claude_code", "dev": "dsh", "qa": "dsh",
    "release": "dsh", "sre": "dsh",
}

# 角色 → 模型维度(GLM 对照实验时切 glm-5.3-flash)
ROLE_MODEL = {
    "dev": "deepseek-v4-flash", "qa": "deepseek-v4-flash",
    "release": "deepseek-v4-flash", "sre": "deepseek-v4-flash",
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

# role 执行失败挂起时的 reason_code;无对应枚举的态给 None(suspend 形参可选)
ROLE_SUSPEND_CODE = {"p4_verifying": "verify_failed", "p5_releasing": "release_failed"}


def _model_for(cfg: dict | None, role: str) -> str | None:
    """cfg["models"][role] 优先,ROLE_MODEL 兜底(无配置的角色为 None)。
    yaml 空 `models:` 段解析为 None,与 gateway 的 (cfg.get("gateway") or {}) 防御对齐。"""
    return ((cfg or {}).get("models") or {}).get(role) or ROLE_MODEL.get(role)


def _record_cost(pool: Path, ticket, adapter: HarnessAdapter, result, role: str) -> None:
    res = ADAPTER_RESOURCE.get(adapter.name)
    if not res:
        return
    resource, unit = res
    if unit == "tokens":
        # 口径只算 input+output:cache_read 等会造成水位虚高,
        # 且 tokens 里混入嵌套 dict 时 sum(values()) 会 TypeError
        amount = result.tokens.get("input_tokens", 0) + result.tokens.get("output_tokens", 0)
    else:
        amount = result.cost_cny
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


def _changed_files(wt: Path) -> list[str]:
    """R7:worktree 内 dev 的改动文件清单(相对项目根,/ 分隔)。
    来源 = `git status --porcelain`(未跟踪+已修改)+ `git diff --name-only <base>`
    (已提交;base 由 ensure_worktree 落盘的 .orc-base 提供,无该文件则退化为仅 status)。
    .orc-base 是编排器记号而非 dev 产物,不计入。"""
    files: list[str] = []
    r = subprocess.run(
        # -uall:未跟踪目录不折叠(否则嵌套新文件以 `?? docs/` 出现,精确 glob 会误判)
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall"],
        cwd=wt, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:          # rename 取新路径
                path = path.split(" -> ", 1)[1]
            if path:
                files.append(path.strip('"'))
    base_file = wt / ".orc-base"
    if base_file.exists():
        base_ref = base_file.read_text(encoding="utf-8").strip()
        if base_ref:
            r = subprocess.run(
                ["git", "-c", "core.quotepath=false", "diff", "--name-only", base_ref],
                cwd=wt, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                files.extend(p for p in (s.strip() for s in r.stdout.splitlines()) if p)
    seen: set[str] = set()
    out: list[str] = []
    for f in files:
        if f != ".orc-base" and f not in seen:
            seen.add(f)
            out.append(f)
    return out


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
                suspend(pool, ticket, "system", reason=f"任务清单装载失败: {e}",
                        reason_code="load_failed")
                return f"suspended: 任务清单装载失败: {e}"
            save_ticket(pool, ticket)
    ready = ready_tasks(ticket.tasks)
    if not ready:
        if all(t["status"] == "done" for t in ticket.tasks):
            transition(pool, ticket, "p4_verifying", actor="system")
            return "auto: p4_verifying"
        suspend(pool, ticket, actor="system",
                reason="无可派发任务且未完成:依赖死锁或依赖缺失",
                reason_code="deadlock")
        return "suspend: 依赖死锁"
    # 成本闸在完工判定之后:全 done 工单优先进 p4,不得被帽挂起(T1 评审观察)
    if cfg and ds_daily_exceeded(pool, cfg):
        return "blocked: ds 日现金线"
    if ds_ticket_cost(pool, ticket.id) > (ticket.budget or {}).get("token_cap_cny", 10.0):
        suspend(pool, ticket, actor="system", reason="工单预算帽",
                reason_code="budget_cap")
        return "suspend: 工单预算帽"
    task = ready[0]
    wt = ensure_worktree(project_dir, f"{ticket.id}-{task['id']}")
    packet = make_packet(task, ticket, wt, design_excerpt="")
    packet.model = _model_for(cfg, "dev")
    if task["attempts"] > 0:
        packet.prompt = retry_prompt(task, packet.prompt, task.get("last_error", ""))
    result = adapter.run(packet)
    task["attempts"] += 1
    if cfg:
        # DS 现金不分成败:失败/被复检打回的尝试照样烧钱,每次调用都入账
        _record_cost(pool, ticket, adapter, result, "dev")
    verify = None
    if result.status == "done" and task.get("scope"):
        # R7 scope 越界强制检查:dev done 后、验收前先拦——越界属致命,不必再烧验收
        violations = scope_violations(_changed_files(wt), task["scope"])
        if violations:
            verify = "failed"
            result.status = "failed"
            # FAIL: 行置顶(D5 约定),走既有重试阶梯,dev 下一轮直接看到越界文件列表
            result.output = (
                f"FAIL: scope 越界: {', '.join(violations)}\n"
                f"--- harness 输出(截断) ---\n{result.output[:500]}"
            )
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
                # 复检证据在前:事件 [:500] 与 retry_prompt [:800] 切头时证据不丢
                tail = (r.stdout + r.stderr)[-1000:]
                result.output = (
                    f"[acceptance 复检失败 exit={r.returncode}] {tail}\n"
                    f"--- harness 输出(截断) ---\n{result.output[:500]}"
                )
    append_event(pool, ticket.id, "dev", "task_run", task=task["id"],
                 attempt=task["attempts"], status=result.status,
                 tokens=result.tokens, cost_cny=result.cost_cny,
                 output=result.output[:500], verify=verify)
    if result.status == "done":
        task["status"] = "done"
        save_ticket(pool, ticket)
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
                    reason="k3 配额超线,会诊通道关闭,任务挂起",
                    reason_code="quota_exceeded")
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
    # 会诊后仍失败 → 任务判负(spec §5.2 任务级终点);判负本身不挂工单
    task["status"] = "failed"
    ticket.consult_count += 1
    if ticket.consult_count >= 3:
        suspend(pool, ticket, actor="system",
                reason="连续 3 个任务走到会诊级:疑似设计/切片问题",
                reason_code="consult_exhausted")
        return f"suspend:{task['id']}"
    if not ready_tasks(ticket.tasks) and not all(t["status"] == "done" for t in ticket.tasks):
        # 判负后无 ready 且未完工:没有可推进的任务了(单任务工单/依赖被判负堵死)
        suspend(pool, ticket, actor="system",
                reason=f"任务判负:{task['id']} 会诊后仍失败,无 ready 任务可派",
                reason_code="circuit_exhausted")
        return "suspend: 任务判负"
    save_ticket(pool, ticket)
    return f"task_failed:{task['id']}"


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
        model=_model_for(cfg, role),
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
            suspend(pool, t, actor="system", reason=f"发布失败: {result.status}",
                    reason_code="release_failed")
            from orchestrator.daemon.ticket import new_ticket as _nt
            inc = _nt(pool, t.project, f"发布失败: {t.id} {t.summary}",
                      created_by="system", type="incident", related_ticket=t.id)
            # 原单事件流回链:从事故单 related_ticket 与原单 incident_created 双向可查
            append_event(pool, t.id, "system", "incident_created", incident=inc.id)
        else:
            suspend(pool, t, actor="system", reason=f"{role} 执行失败: {result.status}",
                    reason_code=ROLE_SUSPEND_CODE.get(t.state))
    return f"role:{role}:{result.status}"
