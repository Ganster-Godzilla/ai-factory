"""双资源台账:pool/ledger.jsonl,append-only。k3=周配额(tokens),DeepSeek=现金(cny)。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _path(pool: Path) -> Path:
    return pool / "ledger.jsonl"


def append_ledger(pool: Path, resource: str, amount: float, unit: str,
                  ticket_id: str, role: str, model: str) -> dict:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "resource": resource, "amount": amount, "unit": unit,
        "ticket": ticket_id, "role": role, "model": model,
    }
    p = _path(pool)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _entries(pool: Path) -> list[dict]:
    p = _path(pool)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def k3_week_tokens(pool: Path, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    total = 0
    for e in _entries(pool):
        if e["resource"] != "k3" or e["unit"] != "tokens":
            continue
        ts = datetime.fromisoformat(e["ts"])
        if ts.isocalendar()[:2] == (year, week):
            total += int(e["amount"])
    return total


def ds_day_cost(pool: Path, day=None) -> float:
    day = day or datetime.now(timezone.utc).date()
    return sum(
        float(e["amount"])
        for e in _entries(pool)
        if e["resource"] == "deepseek" and e["unit"] == "cny"
        and datetime.fromisoformat(e["ts"]).date() == day
    )


def ds_ticket_cost(pool: Path, ticket_id: str) -> float:
    return sum(
        float(e["amount"])
        for e in _entries(pool)
        if e["resource"] == "deepseek" and e["unit"] == "cny" and e["ticket"] == ticket_id
    )


def k3_budget_exceeded(pool: Path, cfg: dict) -> bool:
    return k3_week_tokens(pool) > cfg["budgets"]["k3_week_token_budget"]


def ds_daily_exceeded(pool: Path, cfg: dict) -> bool:
    return ds_day_cost(pool) > cfg["budgets"]["ds_daily_cny"]
