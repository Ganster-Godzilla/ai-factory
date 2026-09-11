"""可视化办公室数据聚合(T-2026-0911-004 阶段1,只读)。

六岗位映射 + 岗位详情 + 气泡动态,全部来自 pool 工单 yaml/事件流——
只读查询,零写入,前端不得据此改状态。状态语义(对齐 Codex 方案第4节):
无心跳,只显示"阶段+最近更新时间",不假装"在线正在工作"。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from orchestrator.dashboard import views
from orchestrator.daemon.events import read_events

# 六岗位定义(对应编排器 WORK_STATES);昵称可配,岗位恒显
ROLES = [
    {"key": "pm", "title": "PM", "nick": "王经理", "states": ["p1_drafting"]},
    {"key": "architect", "title": "架构师", "nick": "钱工", "states": ["p2_designing"]},
    {"key": "dev", "title": "开发", "nick": "陈工", "states": ["p3_running"]},
    {"key": "qa", "title": "QA", "nick": "赵审", "states": ["p4_verifying"]},
    {"key": "release", "title": "发布", "nick": "刘市", "states": ["p5_ready", "p5_releasing"]},
    {"key": "sre", "title": "SRE", "nick": "孙维", "states": ["monitoring"]},
]

# 事件 → 一句话气泡(结构化生成,不展示模型推理)
def _bubble(ev: dict) -> str:
    e = ev.get("event", "")
    task = ev.get("task", "")
    if e == "task_run":
        return f"任务 {task} {ev.get('status','')}"
    if e == "role_run":
        return f"{ev.get('status','执行')}"
    if e == "gate_failed":
        return f"门禁未过 {len(ev.get('missing', []))} 项"
    if e == "state_changed":
        return f"进入 {ev.get('to','')}"
    if e == "suspended":
        return f"挂起:{ev.get('reason','')[:20]}"
    if e == "verdict":
        return f"验收 {ev.get('verdict','')}"
    if e == "consult":
        return f"会诊 {task} {ev.get('status','')}"
    return e or "活动"


def _ticket_card(pool: Path, t) -> dict:
    """一张工单卡片:目标/阶段/最近更新/阻塞/最近两条动态/产物键。"""
    evs = read_events(pool, t.id)
    last_ts = evs[-1]["ts"] if evs else t.created_at
    bubbles = [_bubble(e) for e in evs[-2:]] if evs else []
    blocked = None
    if t.state == "suspended":
        sev = next((e for e in reversed(evs) if e.get("event") == "suspended"), None)
        blocked = (sev or {}).get("reason", "挂起")
    return {
        "id": t.id,
        "project": t.project,
        "summary": t.summary[:60],
        "state": t.state,
        "last_update": last_ts,
        "blocked": blocked,
        "bubbles": bubbles,
        "artifacts": list((t.artifacts or {}).keys()),
        "tasks_done": sum(1 for x in (t.tasks or []) if x.get("status") == "done"),
        "tasks_total": len(t.tasks or []),
    }


def office_data(pool: Path, cfg: dict, project: str | None = None) -> dict:
    """办公室一页数据:六岗位(各扛哪些工单卡)+ 顶部 KPI + 项目清单 + 同步时间。"""
    tickets = views._all_tickets(pool)
    if project:
        tickets = [t for t in tickets if t.project == project]
    state_to_role = {s: r["key"] for r in ROLES for s in r["states"]}
    # 挂起工单归到"等待你/阻塞",不进岗位工位(岗位只显示在跑阶段)
    by_role = {r["key"]: [] for r in ROLES}
    attention = []   # 待你处理:审批中 + 挂起
    for t in tickets:
        if t.state in ("done", "closed", "draft"):
            continue
        if t.state == "suspended":
            attention.append(_ticket_card(pool, t))
            continue
        rk = state_to_role.get(t.state)
        if rk:
            by_role[rk].append(_ticket_card(pool, t))
        # 待审批(approve 边)也进 attention
        if t.state in ("p0_proposed", "p1_proposed", "p5_ready") or \
           (t.state == "p2_designing" and getattr(t, "owner_role", None) == "boss"):
            attention.append(_ticket_card(pool, t))

    roles_out = []
    for r in ROLES:
        cards = by_role[r["key"]]
        roles_out.append({
            **r,
            "count": len(cards),
            "tickets": cards,
            # 无心跳:状态只到"有 N 单在 X 阶段"或"空闲"
            "status": "active" if cards else "idle",
        })

    ov = views.overview_data(pool, cfg)
    projects = sorted({t.project for t in views._all_tickets(pool)})
    return {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "projects": projects,
        "kpi": {
            "running": ov["running"],
            "pending_approval": ov["pending_approval"],
            "suspended": ov["suspended"],
            "today_done": ov["today_events"].get("done", 0),
            "ds_today": ov["ds_today"],
        },
        "roles": roles_out,
        "attention": sorted(attention, key=lambda c: c["last_update"], reverse=True)[:10],
    }
