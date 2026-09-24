"""工单:pool 中的状态权威对象。YAML 序列化,字段见 spec 第 2 节。

CAS 硬门(T-2026-0921-004 O1):每个 load 的对象带盘上内容指纹(内存私有
_disk_fp,绝不序列化);save_ticket 在按票锁内比对——盘上指纹≠对象指纹
=有人在我加载后写过(lost-update),StaleTicketError 响亮抛出,不合并不
重试。保存成功后指纹自更新,同对象连存不误伤;手工构造(无指纹)首存
=创建语义不受闸。
"""
from __future__ import annotations

import hashlib
import os, time
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from orchestrator.daemon.events import append_event


class StaleTicketError(Exception):
    """盘上指纹≠对象指纹:lost-update 拦截(0921-004 事故根治,响亮失败)。"""

VALID_STATES = {
    "draft", "p0_proposed", "p1_drafting", "p1_proposed", "p2_designing",
    "p2_approved", "p3_queued", "p3_running", "p4_verifying",
    "p5_ready", "p5_releasing", "monitoring", "done", "suspended", "closed",
}
VALID_TYPES = {"feature", "incident"}
# 任务分级(T-2026-0829-006):L1 完整流程 / L2(字段合法,本单行为同 L1)/ L3 快速通道
VALID_LEVELS = {"L1", "L2", "L3"}
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
    related_ticket: str | None = None   # 事故单回链原单 id(P5 发布失败自动建单时写入)
    p1_round: int = 0   # P1 重做轮次(D2):驳回回炉次数,只增不清;旧 yaml 缺字段时默认 0 兜底
    created_at: str | None = None   # 建单时刻 UTC ISO(T-2026-0829-001 D3):None=存量单,新门禁不追溯
    level: str = "L1"   # 任务分级(T-2026-0829-006):缺省 L1 保守;存量 yaml 无字段 load 自然兜底

    @classmethod
    def load(cls, path: Path) -> "Ticket":
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        # 忽略未知键:integration 线可能写入更新的字段(如 p1_round),
        # main 线加载不应崩——否则整个 dashboard 对真实 pool 全 500(2026-08-29 事故)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        t = cls(**known)
        t._disk_fp = _fingerprint(text)  # CAS 指纹:内存私有,不随 asdict 序列化
        return t

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
        if self.level not in VALID_LEVELS:
            problems.append(f"level 非法: {self.level}")
        return problems


def _path(pool: Path, ticket_id: str) -> Path:
    # 拼路径前校验 id:堵住 %5C 反斜杠路径遍历面(dashboard /ticket/<id> 直达这里)
    if not ID_RE.match(ticket_id):
        raise ValueError(f"ticket id 格式非法: {ticket_id!r}")
    return pool / "tickets" / f"{ticket_id}.yaml"


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ticket_lock(pool: Path, ticket_id: str) -> Path:
    """按票文件锁(O_EXCL 自旋,与 _locked 同范式;锁内完成 CAS 校验+写盘,
    关死 check-then-write 的 TOCTOU 窗)。"""
    (pool / "tickets").mkdir(parents=True, exist_ok=True)  # 首存时目录可能未建
    lock = pool / "tickets" / f"{ticket_id}.lock"
    for _ in range(50):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return lock
        except FileExistsError:
            time.sleep(0.1)
    raise TimeoutError(f"ticket 锁超时: {ticket_id}")


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
               type: str = "feature", related_ticket: str | None = None,
               level: str = "L1") -> Ticket:
    lock = _locked(pool)
    try:
        t = Ticket(
            id=_next_id(pool), type=type, project=project,
            state="p1_drafting" if type == "incident" else "draft",
            owner_role="pm", summary=summary, created_by=created_by,
            priority="high" if type == "incident" else "normal",
            related_ticket=related_ticket,
            created_at=datetime.now(timezone.utc).isoformat(),
            level=level,
        )
        save_ticket(pool, t)
        append_event(pool, t.id, created_by, "created", summary=summary)
        return t
    finally:
        lock.unlink()


def load_ticket(pool: Path, ticket_id: str) -> Ticket:
    return Ticket.load(_path(pool, ticket_id))


def _validate_tasks(tasks: list) -> list[str]:
    """tasks 契约(T-2026-0903-010):每项须为 dict 且含非空 id 键。
    手写裸串 ["S1", ...] 曾致详情页 500 / ready_tasks 炸——写入层快速失败拒入。"""
    problems = []
    for i, x in enumerate(tasks or []):
        if not isinstance(x, dict) or not x.get("id"):
            problems.append(f"tasks[{i}] 契约违例:须为 dict 且含非空 id,收到 {x!r}")
    return problems


def save_ticket(pool: Path, ticket: Ticket) -> None:
    problems = ticket.validate() + _validate_tasks(ticket.tasks)
    if problems:
        raise ValueError(f"工单校验失败: {problems}")
    path = _path(pool, ticket.id)
    lock = _ticket_lock(pool, ticket.id)
    try:
        fp = getattr(ticket, "_disk_fp", None)
        if fp is not None:
            # CAS:盘上在我加载后被人改过(或票被删)→响亮拒绝,不合并不重试
            if not path.exists():
                raise StaleTicketError(
                    f"{ticket.id} 盘上文件已不存在(持旧对象保存=重建幽灵票,拒)")
            if _fingerprint(path.read_text(encoding="utf-8")) != fp:
                raise StaleTicketError(
                    f"{ticket.id} 盘上已被他人改写(lost-update 拦截);"
                    f"请重新 load 后再写")
        ticket.save(path)
        # 指纹自更新:同对象连存不误伤
        ticket._disk_fp = _fingerprint(path.read_text(encoding="utf-8"))
    finally:
        lock.unlink(missing_ok=True)
