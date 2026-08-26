"""Append-only 事件日志。每工单一个 JSONL 文件,只追加不修改。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _path(pool: Path, ticket_id: str) -> Path:
    return pool / "tickets" / f"{ticket_id}.events.jsonl"


def append_event(pool: Path, ticket_id: str, actor: str, event: str, **fields) -> dict:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticket": ticket_id,
        "actor": actor,
        "event": event,
        **fields,
    }
    path = _path(pool, ticket_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_events(pool: Path, ticket_id: str) -> list[dict]:
    path = _path(pool, ticket_id)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
