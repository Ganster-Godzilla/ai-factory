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
from orchestrator.daemon.ledger import append_ledger, ds_day_cost, ds_ticket_cost
from orchestrator.daemon.slicer import load_task_list, make_packet, ready_tasks, scope_violations
from orchestrator.daemon.statemachine import suspend, transition
from orchestrator.daemon.ticket import load_ticket, save_ticket
from orchestrator.daemon.worktree import ensure_worktree

ROLE_ROUTING = {
    "pm": "claude_code", "architect": "claude_code", "test_designer": "claude_code",
    "qa_vision": "claude_code", "dev": "claude_code", "qa": "claude_code",
    "release": "claude_code", "sre": "claude_code",
    # T-2026-0902-009(B 方案,boss 决策):P3 执行层全切 k3 订阅池(claude -p 经 relay,
    # 溢出梯 kimi1-4→glm→ds→zen-k3 在 relay 侧,runner 零感知);DS 现金耗尽,
    # dsh 适配器保留作回退路径(回本表四行即切回)。
}

# 角色 → 模型维度(仅 dsh 路径使用;claude_code 适配器不读 model,relay 侧自选/重写)
ROLE_MODEL = {
    "dev": "deepseek-v4-flash", "qa": "deepseek-v4-flash",
    "release": "deepseek-v4-flash", "sre": "deepseek-v4-flash",
}

# 角色级超时(秒):release 要写发布记录+跑完整部署链(构建/上传/翻转/重启/冒烟),
# 1800s 在 007 实证被打死;其余角色沿用 TaskPacket 缺省 1800
ROLE_TIMEOUT = {"release": 3600}

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


def _mingfang(cfg: dict | None) -> bool:
    """明放开关(T-2026-0829-004):budgets.mingfang_mode 显式 true 才放行;
    缺键/缺 budgets 一律硬闸(向后兼容)。必须 is True:yaml 里写 "false"(带引号)
    是字符串,bool() 会误判为真——安全开关不许反向失效(评审 F3)。"""
    return ((cfg or {}).get("budgets") or {}).get("mingfang_mode") is True


def _record_cost(pool: Path, ticket, adapter: HarnessAdapter, result, role: str) -> None:
    res = ADAPTER_RESOURCE.get(adapter.name)
    if not res:
        return
    resource, unit = res
    # 台账统一口径 D3:tokens 只留 {"input","output"} 两键(k3 侧来自 claude JSON usage,
    # dsh 侧来自 usage trailer,键名归一);amount 不变:k3=input+output,ds=cost_cny
    tokens = {"input": int(result.tokens.get("input_tokens") or 0),
              "output": int(result.tokens.get("output_tokens") or 0)}
    if unit == "tokens":
        # 口径只算 input+output:cache_read 等会造成水位虚高,
        # 且 tokens 里混入嵌套 dict 时 sum(values()) 会 TypeError
        amount = tokens["input"] + tokens["output"]
    else:
        amount = result.cost_cny
    # 三字段齐全才是一条完整账:0 元调用(GLM 体验卡)也留 calls 证据;
    # 明放估算(T-2026-0829-004):amount>0 且 estimated 时透传标记
    if amount or tokens["input"] or tokens["output"]:
        append_ledger(pool, resource, amount, unit, ticket.id, role, adapter.name,
                      tokens=tokens, calls=1,
                      estimated=getattr(result, "estimated", False))


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


def _transition_gated(pool: Path, t, to_state: str, actor: str,
                      project_dir: Path) -> str | None:
    """runner 自动边的门禁接线(T-2026-0829-001 M4):
    GateFailed(结构化,评审 R3-3)→ gate_failed 事件(missing 清单)+
    suspend(artifact_missing);project_dir 缺失等其他 IllegalTransition 照常抛。"""
    from orchestrator.daemon.statemachine import GateFailed
    try:
        transition(pool, t, to_state, actor=actor, project_dir=project_dir)
        return None
    except GateFailed as e:
        append_event(pool, t.id, "system", "gate_failed", to=to_state,
                     missing=e.fails)
        suspend(pool, t, actor="system",
                reason=f"产物门禁未过({to_state}): "
                       f"{e.fails[0] if e.fails else e}",
                reason_code="artifact_missing")
        return f"suspend: 产物门禁未过({to_state})"


def run_dev_tasks(pool: Path, ticket, adapter: HarnessAdapter,
                  project_dir: Path, cfg: dict | None = None,
                  consult_adapter: HarnessAdapter | None = None) -> str:
    if not ticket.tasks:
        # 架构师产物 lazy-load:统一解析器定位 02_设计文档/tasks.yaml(T-2026-0830-001 F6)
        from orchestrator.daemon.artifacts import resolve_artifact_path
        rel = resolve_artifact_path(
            project_dir, "document/business/{tid_dir}/02_设计文档/tasks.yaml",
            ticket.id)
        spec = project_dir / rel if rel else project_dir / "__none__"
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
            blocked = _transition_gated(pool, ticket, "p4_verifying", "system",
                                        project_dir)
            if blocked:
                return blocked
            return "auto: p4_verifying"
        suspend(pool, ticket, actor="system",
                reason="无可派发任务且未完成:依赖死锁或依赖缺失",
                reason_code="deadlock")
        return "suspend: 依赖死锁"
    # 成本闸在完工判定之后:全 done 工单优先进 p4,不得被帽挂起(T1 评审观察)
    # 明放模式(T-2026-0829-004):mingfang_mode 下双闸降级为 budget_warn 事件放行;
    # 缺省/关闭维持硬闸。配置即决策留痕(orchestrator.yaml 标注磨合期+复审日)
    mingfang = _mingfang(cfg)
    if cfg:
        day_cost = ds_day_cost(pool)
        daily_cap = (cfg.get("budgets") or {}).get("ds_daily_cny", 30)
        if day_cost > daily_cap:
            if not mingfang:
                return "blocked: ds 日现金线"
            append_event(pool, ticket.id, "system", "budget_warn", gate="ds_daily",
                         value=round(day_cost, 4), threshold=daily_cap)
    ticket_cost = ds_ticket_cost(pool, ticket.id)
    cap = (ticket.budget or {}).get("token_cap_cny", 10.0)
    if ticket_cost > cap:
        if not mingfang:
            suspend(pool, ticket, actor="system", reason="工单预算帽",
                    reason_code="budget_cap")
            return "suspend: 工单预算帽"
        append_event(pool, ticket.id, "system", "budget_warn", gate="ticket_cap",
                     value=round(ticket_cost, 4), threshold=cap)
    task = ready[0]
    wt = ensure_worktree(project_dir, f"{ticket.id}-{task['id']}")
    packet = make_packet(task, ticket, wt, design_excerpt="")
    packet.model = _model_for(cfg, "dev")
    if task["attempts"] > 0:
        packet.prompt = retry_prompt(task, packet.prompt, task.get("last_error", ""))
    result = adapter.run(packet)
    task["attempts"] += 1
    # 累计计数(T-2026-0901-003):修复重跑会清零 attempts,看板失真
    # (003-S6 实败 23 次显示 1)——attempts_total 只增不减,事件流之外的快查口
    task["attempts_total"] = int(task.get("attempts_total", 0)) + 1
    if result.usage_missing:
        # 明放(T-2026-0829-004):无 trailer 按 returncode 推进+估算入账,事件留痕供审计
        append_event(pool, ticket.id, "dev", "usage_missing", task=task["id"],
                     output=result.output[:500])
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
        # 验收超时独立分级(009-S6 实证):回归链 33 段 ~1000s+,固定 600s 必超时误判。
        # task.acceptance_timeout 优先,缺省跟随 task.timeout,再缺省 600,上限 7200
        acc_timeout = min(int(task.get("acceptance_timeout")
                              or task.get("timeout") or 600), 7200)
        try:
            r = _run_acceptance(task["acceptance_cmd"], wt, timeout=acc_timeout)
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
    if verify is not None:
        # 验收留痕持久化(T-2026-0829-001 D6):P3 门禁直读工单 yaml,不回放事件流
        task["verify"] = verify
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
            # T-2026-0902-009:P3 全切 k3 池后水位含 runner 流量,观察期(至 2026-09-09)
            # 与 DS 明放同款 warn-only:超线写 budget_warn 放行,不卡 pipeline;
            # 复审按 relay 真实曲线决定恢复硬闸或定阈值。mingfang_mode 关闭即恢复硬闸。
            if (cfg.get("budgets") or {}).get("mingfang_mode"):
                append_event(pool, ticket.id, "system", "budget_warn",
                             note="k3 周水位超线(观察期 warn-only,T-2026-0902-009)")
            else:
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
        timeout=ROLE_TIMEOUT.get(role, 1800),
    )
    result = adapter.run(packet)
    if result.usage_missing:
        # dsh 角色路径(qa/release/sre)明放同款:无 trailer 推进+估算,事件留痕
        append_event(pool, t.id, role, "usage_missing", output=result.output[:500])
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
            blocked = _transition_gated(
                pool, t, SUCCESS_NEXT[t.state],
                "system" if t.state == "p3_running" else role, project_dir)
            if blocked:
                return blocked
    else:
        if t.state == "p5_releasing":
            suspend(pool, t, actor="system", reason=f"发布失败: {result.status}",
                    reason_code="release_failed")
            # 事故单收口到 incident.create_incident(T-2026-0901-021 去重:
            # 已有未关闭 incident 时复用,重试循环不再雪崩建单);双向留痕不变
            from orchestrator.daemon.incident import create_incident as _ci
            _ci(pool, t, f"发布失败: {t.id} {t.summary}")
        else:
            suspend(pool, t, actor="system", reason=f"{role} 执行失败: {result.status}",
                    reason_code=ROLE_SUSPEND_CODE.get(t.state))
    return f"role:{role}:{result.status}"
