"""总览页数据装配:纯函数,可单测。不渲染、不依赖 Flask。"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from orchestrator.daemon.events import read_events
from orchestrator.daemon.gateway import k3_effective_week_tokens
from orchestrator.daemon.ledger import ds_day_cost, ds_ticket_cost
from orchestrator.daemon.ticket import Ticket, VALID_STATES, load_ticket

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


# 泳道图列定义:顺序即流水线顺序;closed/done 不进泳道(歧义澄清 #5)
SWIMLANE_COLUMNS = [
    ("p0", "P0 提案", {"draft", "p0_proposed"}),
    ("p1", "P1 需求", {"p1_drafting", "p1_proposed"}),
    ("p2", "P2 设计", {"p2_designing", "p2_approved"}),
    ("p3", "P3 执行", {"p3_queued", "p3_running"}),
    ("p4", "P4 验证", {"p4_verifying"}),
    ("p5", "P5 发布", {"p5_ready", "p5_releasing"}),
    ("mon", "监控", {"monitoring"}),
    ("susp", "挂起", {"suspended"}),
]
_STATE_TO_COL = {s: key for key, _, states in SWIMLANE_COLUMNS for s in states}

_VALID_SORTS = {"id_desc", "id_asc", "mtime_desc"}


def _ticket_mtimes(pool: Path) -> dict[str, float]:
    """按 glob 真实文件名取 mtime(键=文件 stem),不用工单内容里的 id 拼路径:
    手改 id/文件名不一致时 stat 不会炸掉整页(评审 A3)。"""
    tickets_dir = pool / "tickets"
    if not tickets_dir.exists():
        return {}
    return {p.stem: p.stat().st_mtime for p in tickets_dir.glob("*.yaml")}


def ticket_list(pool: Path, project: str | None = None, state: str | None = None,
                q: str | None = None, sort: str = "id_desc") -> dict:
    """工单中心装配:过滤(项目/状态/关键词)+排序。非法参数忽略回默认。"""
    tickets = _all_tickets(pool)
    projects = sorted({t.project for t in tickets if t.project})
    states = sorted(VALID_STATES)

    if project in projects:
        tickets = [t for t in tickets if t.project == project]
    else:
        project = None
    if state in VALID_STATES:
        tickets = [t for t in tickets if t.state == state]
    else:
        state = None
    # 匹配用规范化副本;cur.q 回显用户原输入(评审:搜索框不应被改写)
    needle = (q or "").strip().lower()
    if needle:
        tickets = [t for t in tickets if needle in t.id.lower()
                   or needle in (t.summary or "").lower()]   # summary 可为 None(A2)
    if sort not in _VALID_SORTS:
        sort = "id_desc"

    mtimes = _ticket_mtimes(pool)   # 一次 stat,排序与展示共用
    if sort == "mtime_desc":
        tickets.sort(key=lambda t: mtimes.get(t.id, 0), reverse=True)
    else:
        tickets.sort(key=lambda t: t.id, reverse=(sort == "id_desc"))

    return {
        "tickets": tickets,
        "projects": projects,
        "states": states,
        "mtimes": {t.id: datetime.fromtimestamp(mtimes.get(t.id, 0))
                   .strftime("%m-%d %H:%M") for t in tickets},
        "cur": {"project": project, "state": state, "q": q or "", "sort": sort},
    }


def swimlanes(pool: Path) -> dict:
    """项目中心泳道图:行=项目(含工单全部已完结的项目,对齐 PRD 验收#3),
    列=阶段。closed/done 不落任何列(歧义澄清 #5)。"""
    rows: dict[str, dict[str, list[Ticket]]] = {}
    for t in _all_tickets(pool):
        if not t.project:
            continue
        cells = rows.setdefault(t.project,
                                {key: [] for key, _, _ in SWIMLANE_COLUMNS})
        col = _STATE_TO_COL.get(t.state)
        if col is not None:
            cells[col].append(t)
    return {
        "columns": [{"key": key, "title": title}
                    for key, title, _ in SWIMLANE_COLUMNS],
        "rows": [{"project": p, "cells": rows[p]} for p in sorted(rows)],
    }


def project_strips(pool: Path, tickets: list[Ticket] | None = None,
                   groups: dict | None = None) -> list[dict]:
    """总览项目迷你条:每项目 running/pending/suspended 计数。
    pending 口径与审批中心一致(排除 suspended 组)。
    调用方已加载 tickets/groups 时传入,避免重复扫池(评审 A6)。"""
    tickets = tickets if tickets is not None else _all_tickets(pool)
    groups = groups if groups is not None else pending_groups(pool)
    strips: dict[str, dict] = {}

    def slot(project: str) -> dict:
        return strips.setdefault(project, {"project": project, "running": 0,
                                           "pending": 0, "suspended": 0})

    for t in tickets:
        if not t.project:
            continue
        s = slot(t.project)
        if t.state in RUNNING_STATES:
            s["running"] += 1
        if t.state == "suspended":
            s["suspended"] += 1
    for k, v in groups.items():
        if k == "suspended":
            continue
        for t in v:
            if t.project:
                slot(t.project)["pending"] += 1
    return [strips[p] for p in sorted(strips)]


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

    # GET 高频只读:回退不写 gateway_fallback 事件(终审 F1);留痕留给 runner 配额闸
    k3_used = k3_effective_week_tokens(pool, cfg, trace=False)
    k3_budget = int((cfg.get("budgets") or {}).get("k3_week_token_budget", 0))
    k3_pct = round(k3_used / k3_budget * 100, 1) if k3_budget else 0.0

    # 待审批口径与审批中心一致:pending_groups 派生,排除 suspended 组(终审 F3)
    groups = pending_groups(pool)
    pending = sum(len(v) for k, v in groups.items() if k != "suspended")

    # 明放复审提醒(T-2026-0829-004):mingfang_mode 开启时总览挂提示条;过 review_after 变红。
    # is True:yaml 写 "false"(带引号)不许误判(评审 F3);缺复审日=配置残缺,按过期逼修(评审 F8)
    budgets = cfg.get("budgets") or {}
    mingfang = budgets.get("mingfang_mode") is True
    review_after = str(budgets.get("review_after") or "")
    overdue = False
    if mingfang:
        if not review_after:
            overdue = True
        else:
            try:
                overdue = date.today() > date.fromisoformat(review_after)
            except ValueError:
                overdue = True   # 日期配置损坏:按过期处理,逼人去修配置

    return {
        "k3_used": k3_used,
        "k3_budget": k3_budget,
        "k3_pct": k3_pct,
        "ds_today": ds_day_cost(pool),
        "ds_month": _ds_month_cost(pool),
        "ds_daily_budget": (cfg.get("budgets") or {}).get("ds_daily_cny", 30),
        "pending_approval": pending,
        "running": sum(1 for t in tickets if t.state in RUNNING_STATES),
        "suspended": sum(1 for t in tickets if t.state == "suspended"),
        "today_events": _today_events(pool),
        "project_strips": project_strips(pool, tickets, groups),
        "mingfang_mode": mingfang,
        "mingfang_review_after": review_after if mingfang else "",
        "mingfang_overdue": overdue,
    }
