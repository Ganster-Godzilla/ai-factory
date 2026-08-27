"""工单:pool 中的状态权威对象。YAML 序列化,字段见 spec 第 2 节。"""
from __future__ import annotations

import os, time
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

import yaml

from orchestrator.daemon.events import append_event

VALID_STATES = {
    "draft", "p0_proposed", "p1_drafting", "p1_proposed", "p2_designing",
    "p2_approved", "p3_queued", "p3_running", "p4_verifying",
    "p5_ready", "p5_releasing", "monitoring", "done", "suspended", "closed",
}
VALID_TYPES = {"feature", "incident"}
ID_RE = re.compile(r"^T-\d{4}-\d{4}-\d{3}$")


@dataclass
class Ticket:
    id: str
    type: str
    project: str
    state: str
    owner_role: str
    summary: str = ""
    priority: str = "normal"
    artifacts: dict = field(default_factory=dict)
    tasks: list = field(default_factory=list)
    budget: dict = field(default_factory=lambda: {"token_cap": 500000, "token_cap_cny": 10.0})
    created_by: str = "human"
    resume_state: str | None = None
    consult_count: int = 0   # 会诊后判负的任务数(§5.2:3 个任务判负 → 整单挂起)

    @classmethod
    def load(cls, path: Path) -> "Ticket":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(asdict(self), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )

    def validate(self) -> list[str]:
        problems = []
        if not ID_RE.match(self.id):
            problems.append(f"id 格式非法: {self.id}")
        if self.state not in VALID_STATES:
            problems.append(f"state 非法: {self.state}")
        if self.type not in VALID_TYPES:
            problems.append(f"type 非法: {self.type}")
        return problems


def _path(pool: Path, ticket_id: str) -> Path:
    return pool / "tickets" / f"{ticket_id}.yaml"


def _next_id(pool: Path) -> str:
    today = date.today().strftime("%Y-%m%d")
    seq = 0
    for p in (pool / "tickets").glob(f"T-{today}-*.yaml"):
        seq = max(seq, int(p.stem.rsplit("-", 1)[1]))
    return f"T-{today}-{seq + 1:03d}"


def _locked(pool: Path):
    pool.mkdir(parents=True, exist_ok=True)  # pool 可能尚未创建(CLI 首次 new)
    lock = pool / ".lock"
    for _ in range(50):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return lock
        except FileExistsError:
            time.sleep(0.1)
    raise TimeoutError("pool 锁超时")


def new_ticket(pool: Path, project: str, summary: str, created_by: str = "human",
               type: str = "feature") -> Ticket:
    lock = _locked(pool)
    try:
        t = Ticket(
            id=_next_id(pool), type=type, project=project,
            state="p1_drafting" if type == "incident" else "draft",
            owner_role="pm", summary=summary, created_by=created_by,
            priority="high" if type == "incident" else "normal",
        )
        save_ticket(pool, t)
        append_event(pool, t.id, created_by, "created", summary=summary)
        return t
    finally:
        lock.unlink()


def load_ticket(pool: Path, ticket_id: str) -> Ticket:
    return Ticket.load(_path(pool, ticket_id))


def save_ticket(pool: Path, ticket: Ticket) -> None:
    problems = ticket.validate()
    if problems:
        raise ValueError(f"工单校验失败: {problems}")
    ticket.save(_path(pool, ticket.id))
