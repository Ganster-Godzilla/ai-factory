"""总览页数据装配:纯函数,可单测。不渲染、不依赖 Flask。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.daemon.events import read_events
from orchestrator.daemon.gateway import k3_effective_week_tokens
from orchestrator.daemon.ledger import ds_day_cost, ds_ticket_cost
from orchestrator.daemon.statemachine import APPROVALS
from orchestrator.daemon.ticket import Ticket, load_ticket

# 运行中 = 不需要人盯、流水线正在推进的状态(spec §2)
RUNNING_STATES = {"p3_running", "p4_verifying", "p5_releasing", "monitoring"}


def _ds_month_cost(pool: Path, now: datetime | None = None) -> float:
    """DS 本月现金:ledger 里当月 deepseek/cny 合计(内联 helper,不动 ledger.py)。"""
    now = now or datetime.now(timezone.utc)
    p = pool / "ledger.jsonl"
    if not p.exists():
        return 0.0
    total = 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("resource") != "deepseek" or e.get("unit") != "cny":
            continue
        ts = datetime.fromisoformat(e["ts"])
        if (ts.year, ts.month) == (now.year, now.month):
            total += float(e["amount"])
    return total


def _today_events(pool: Path, now: datetime | None = None) -> dict[str, int]:
    """今日事件摘要:遍历 pool/tickets/*.events.jsonl,当日 ts 事件按工单分组计数。"""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    counts: dict[str, int] = {}
    tickets_dir = pool / "tickets"
    if not tickets_dir.exists():
        return counts
    for path in sorted(tickets_dir.glob("*.events.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if datetime.fromisoformat(e["ts"]).date() != today:
                continue
            tid = e.get("ticket") or path.name.replace(".events.jsonl", "")
            counts[tid] = counts.get(tid, 0) + 1
    return counts


def _all_tickets(pool: Path) -> list[Ticket]:
    tickets = []
    tickets_dir = pool / "tickets"
    if tickets_dir.exists():
        for path in sorted(tickets_dir.glob("*.yaml")):
            tickets.append(Ticket.load(path))
    return tickets


def pending_groups(pool: Path) -> dict[str, list[Ticket]]:
    """审批中心分组:P0 提案 / P1 需求 / P2 设计(owner=boss)/ P5 发布 / 探针草稿 / 挂起。"""
    groups: dict[str, list[Ticket]] = {
        "p0": [], "p1": [], "p2": [], "p5": [], "probe": [], "suspended": [],
    }
    for t in _all_tickets(pool):
        if t.state == "p0_proposed":
            groups["p0"].append(t)
        elif t.state == "p1_proposed":
            groups["p1"].append(t)
        elif t.state == "p2_designing" and t.owner_role == "boss":
            groups["p2"].append(t)
        elif t.state == "p5_ready":
            groups["p5"].append(t)
        elif t.state == "draft" and t.created_by == "probe":
            groups["probe"].append(t)
        elif t.state == "suspended":
            groups["suspended"].append(t)
    return groups


def ticket_detail(pool: Path, ticket_id: str) -> dict:
    """工单详情:全字段 + 任务列表 + 事件流(倒序)+ DS 成本 + 产物指针。
    走 load_ticket:id 非法抛 ValueError、工单不存在抛 FileNotFoundError,
    由 app 层 errorhandler 统一 404(闭合 %5C 遍历:池外同名 yaml 不会被加载)。"""
    t = load_ticket(pool, ticket_id)
    return {
        "ticket": t,
        "tasks": t.tasks,
        "events": list(reversed(read_events(pool, ticket_id))),
        "ds_cost": ds_ticket_cost(pool, ticket_id),
        "artifacts": t.artifacts,
    }


def overview_data(pool: Path, cfg: dict) -> dict:
    """总览页全部指标。gateway 不可达时 k3 水位自动回退本地台账。"""
    tickets = _all_tickets(pool)

    k3_used = k3_effective_week_tokens(pool, cfg)
    k3_budget = int((cfg.get("budgets") or {}).get("k3_week_token_budget", 0))
    k3_pct = round(k3_used / k3_budget * 100, 1) if k3_budget else 0.0

    return {
        "k3_used": k3_used,
        "k3_budget": k3_budget,
        "k3_pct": k3_pct,
        "ds_today": ds_day_cost(pool),
        "ds_month": _ds_month_cost(pool),
        "ds_daily_budget": (cfg.get("budgets") or {}).get("ds_daily_cny", 30),
        "pending_approval": sum(1 for t in tickets if t.state in APPROVALS),
        "running": sum(1 for t in tickets if t.state in RUNNING_STATES),
        "suspended": sum(1 for t in tickets if t.state == "suspended"),
        "today_events": _today_events(pool),
    }
