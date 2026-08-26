# 双 Harness 编排器 M1+M2 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建编排器骨架(工单/状态机/事件日志/FakeHarness/CLI)并打通真实双 harness(claude -p 与 dsh headless)的任务级派发链路。

**Architecture:** Python 守护进程内核(本计划先实现其同步内核,常驻循环在 M3+),文件系统为唯一状态权威(pool/ 下工单 YAML + 事件 JSONL),harness 通过适配器契约接入。M1 用 FakeHarness 跑通全状态机;M2 接入真 harness + worktree 隔离 + 任务切片。

**Tech Stack:** Python 3.11(已在 PATH)、pyyaml、pytest、Git Bash、git worktree、`claude` CLI、`dsh` CLI

**Spec:** `docs/superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md`(M1=第 2/3/7 节骨架部分;M2=第 3/6 节)

## Global Constraints

- 所有文件读写必须 `encoding="utf-8"`,写文件必须 `newline="\n"`(Windows cp936/CRLF 会污染 bash 管道与 JSONL)
- 仓库已 git 化并推送 GitHub(origin = github.com/Ganster-Godzilla/ai-factory),每个 Task 结束必须 commit;M1 结束时 push
- `pool/` 已被 .gitignore;测试中一律用 `tmp_path` 构造临时 pool,不污染真实 pool/
- 不修改 quant-lab / tiktok-ecommerce-ai;M2 验收用 `d:\workspace\tmp\orc-e2e\` 临时项目
- 编排器代码全部在 `orchestrator/`,测试全部在 `tests/orchestrator/`,不动 `tests/` 下现有 bash 测试
- 状态机迁移表、审批门禁与 spec 第 2 节一致;老板审批点仅四处:p0_proposed→p1_drafting、p1_proposed→p2_designing、p2_designing→p2_approved、p5_ready→p5_releasing

---

### Task 1: Python 测试环境与编排器包骨架

**Files:**
- Create: `orchestrator/__init__.py`(空)
- Create: `orchestrator/daemon/__init__.py`(空)
- Create: `orchestrator/adapters/__init__.py`(空)
- Create: `tests/orchestrator/__init__.py`(空)
- Create: `tests/orchestrator/conftest.py`
- Create: `orchestrator.yaml`
- Test: `tests/orchestrator/test_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: `POOL` pytest fixture(临时 pool 目录);`orchestrator.yaml` 配置(后续 Task 读它的字段:`pool`, `projects`, `thresholds.concurrent_max`)

- [ ] **Step 1: 安装依赖**

```bash
pip install pytest pyyaml
```

- [ ] **Step 2: 写冒烟测试**

`tests/orchestrator/test_smoke.py`:

```python
import yaml
from pathlib import Path


def test_orchestrator_yaml_loads():
    cfg = yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))
    assert cfg["pool"] == "pool"
    assert cfg["thresholds"]["concurrent_max"] == 2
```

`tests/orchestrator/conftest.py`:

```python
import pytest


@pytest.fixture
def pool(tmp_path):
    p = tmp_path / "pool"
    (p / "tickets").mkdir(parents=True)
    return p
```

- [ ] **Step 3: 创建包骨架与配置**

三个空 `__init__.py`(orchestrator/、daemon/、adapters/)、tests/orchestrator/__init__.py。

`orchestrator.yaml`(仓库根部):

```yaml
pool: pool
projects: {}            # M2 验收时登记:orc-e2e: d:/workspace/tmp/orc-e2e
thresholds:
  concurrent_max: 2
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest tests/orchestrator/ -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/ tests/orchestrator/ orchestrator.yaml
git commit -m "feat(orchestrator): 包骨架 + pytest 环境 + 平台配置"
```

---

### Task 2: 仓库重构 —— 插件库挪入 plugin/

**Files:**
- Move: `skills/ hooks/ agents/ templates/ scripts/` → `plugin/` 下
- Move: `.claude-plugin/plugin.json` → `plugin/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`(`source: "./"` → `"./plugin"`)
- Modify: `docs/distribution.md`(删除"本目录本地不做 git 管理"段落,改为 git+GitHub 主通道)
- Modify: `docs/architecture.md`(加"平台层"一节)
- Modify: `tests/test_init.sh`、`tests/e2e.sh`、`tests/validate_plugin.sh` 中对 `scripts/`、`templates/` 的引用路径(逐一 grep 修正)

**Interfaces:**
- Consumes: 现有仓库布局
- Produces: 后续所有 Task 依赖的顶层布局:`plugin/`(插件)、`orchestrator/`(平台)、`pool/`(运行时)

说明:hooks.json 用 `${CLAUDE_PLUGIN_ROOT}` 引用 scripts,随 plugin/ 整体挪位后**不需要改**;init-project.sh 用 `$ROOT/templates`($ROOT=脚本上一级),scripts 与 templates 一起挪,**也不需要改**。marketplace.json 留在仓库根 `.claude-plugin/`,只改 source 指向。

- [ ] **Step 1: 挪位**

```bash
mkdir -p plugin/.claude-plugin
git mv skills hooks agents templates scripts plugin/
git mv .claude-plugin/plugin.json plugin/.claude-plugin/plugin.json
```

- [ ] **Step 2: 改 marketplace.json**

```json
{
  "name": "ai-factory-local",
  "owner": { "name": "william.dai" },
  "plugins": [
    {
      "name": "ai-factory",
      "source": "./plugin",
      "version": "0.2.0",
      "description": "可复用 AI 工程架构:Phase 0-5 流程技能 + 状态机 + 规则强制分级(E0-E3) + 成长闭环。初始化: /ai-factory:ai-init"
    }
  ]
}
```

- [ ] **Step 3: 修正 tests/ 下的路径引用**

```bash
grep -rn 'scripts/\|templates/' tests/*.sh
```

逐处把 `scripts/` 改为 `plugin/scripts/`、`templates/` 改为 `plugin/templates/`(注意相对起点是仓库根)。

- [ ] **Step 4: 跑插件测试套件验证**

```bash
bash tests/run_all.sh && bash tests/validate_plugin.sh
```

Expected: 全 PASS

- [ ] **Step 5: 更新两份文档**

distribution.md:把"通道二"里"注:本目录本地不做 git 管理"的说明替换为"本仓库已 git 化并托管于 GitHub(私有),git push 即发布"。architecture.md 末尾加一节:

```markdown
## 平台层(2026-08 新增)
本仓库同时是双 harness 编排器平台:根部 orchestrator/(守护进程)、pool/(运行时状态,gitignore)、orchestrator.yaml(平台配置)。插件库在 plugin/ 子目录,分发机制不变。设计规格:docs/superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md
```

- [ ] **Step 6: Commit + push**

```bash
git add -A
git commit -m "refactor: 插件库挪入 plugin/,仓库升级为平台顶层"
git push
```

---

### Task 3: 事件日志 events.py

**Files:**
- Create: `orchestrator/daemon/events.py`
- Test: `tests/orchestrator/test_events.py`

**Interfaces:**
- Produces:
  - `append_event(pool: Path, ticket_id: str, actor: str, event: str, **fields) -> dict`
  - `read_events(pool: Path, ticket_id: str) -> list[dict]`
  - 事件文件路径约定:`pool/tickets/<ticket_id>.events.jsonl`

- [ ] **Step 1: 写失败测试**

```python
from orchestrator.daemon.events import append_event, read_events


def test_append_and_read(pool):
    append_event(pool, "T-2026-0819-001", "pm", "created", detail="探针草稿")
    append_event(pool, "T-2026-0819-001", "boss", "approved")
    events = read_events(pool, "T-2026-0819-001")
    assert [e["event"] for e in events] == ["created", "approved"]
    assert events[0]["actor"] == "pm"
    assert events[0]["detail"] == "探针草稿"
    assert "ts" in events[0]


def test_read_missing_returns_empty(pool):
    assert read_events(pool, "T-0000-0000-000") == []


def test_append_is_append_only(pool):
    append_event(pool, "T-1", "pm", "a")
    append_event(pool, "T-1", "pm", "b")
    assert len(read_events(pool, "T-1")) == 2
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest tests/orchestrator/test_events.py -v
```

Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/events.py tests/orchestrator/test_events.py
git commit -m "feat(orchestrator): append-only 事件日志"
```

---

### Task 4: 工单 ticket.py

**Files:**
- Create: `orchestrator/daemon/ticket.py`
- Test: `tests/orchestrator/test_ticket.py`

**Interfaces:**
- Consumes: 无(被 statemachine/runner/cli 使用)
- Produces:
  - `Ticket` dataclass,字段:`id, type, project, state, owner_role, priority, artifacts, tasks, budget, created_by, resume_state`
  - `Ticket.load(path: Path) -> Ticket`、`ticket.save(path: Path) -> None`、`ticket.validate() -> list[str]`(返回问题列表,空=合法)
  - `new_ticket(pool: Path, project: str, summary: str, created_by: str = "human") -> Ticket`(生成 id `T-YYYY-MMDD-NNN`,NNN 当日自增;落盘 YAML + 追加 created 事件,state=draft,owner_role=pm)
  - `load_ticket(pool: Path, ticket_id: str) -> Ticket`、`save_ticket(pool: Path, ticket: Ticket) -> None`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from orchestrator.daemon.ticket import Ticket, new_ticket, load_ticket, save_ticket


def test_new_ticket_defaults(pool):
    t = new_ticket(pool, project="quant-lab", summary="补测试", created_by="probe")
    assert t.state == "draft"
    assert t.owner_role == "pm"
    assert t.type == "feature"
    assert t.priority == "normal"
    assert t.budget == {"token_cap": 500000}
    assert t.id.startswith("T-")
    assert load_ticket(pool, t.id).summary == "补测试"


def test_validate_catches_bad(pool):
    t = new_ticket(pool, project="quant-lab", summary="x")
    t.state = "not_a_state"
    problems = t.validate()
    assert any("state" in p for p in problems)


def test_save_and_load_roundtrip(pool):
    t = new_ticket(pool, project="quant-lab", summary="x")
    t.tasks = [{"id": "task-1", "status": "pending", "depends_on": []}]
    save_ticket(pool, t)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["id"] == "task-1"
    assert t2.resume_state is None


def test_id_increments(pool):
    a = new_ticket(pool, project="p", summary="a")
    b = new_ticket(pool, project="p", summary="b")
    assert a.id != b.id
```

注:Ticket 增加 `summary` 字段(spec 骨架的补充,审批列表要显示);validate 校验 state 在合法集合内、type ∈ {feature, incident}、id 格式。

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现**

```python
"""工单:pool 中的状态权威对象。YAML 序列化,字段见 spec 第 2 节。"""
from __future__ import annotations

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
    budget: dict = field(default_factory=lambda: {"token_cap": 500000})
    created_by: str = "human"
    resume_state: str | None = None

    @classmethod
    def load(cls, path: Path) -> "Ticket":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(asdict(self), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
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


def new_ticket(pool: Path, project: str, summary: str, created_by: str = "human") -> Ticket:
    t = Ticket(
        id=_next_id(pool), type="feature", project=project,
        state="draft", owner_role="pm", summary=summary, created_by=created_by,
    )
    save_ticket(pool, t)
    append_event(pool, t.id, created_by, "created", summary=summary)
    return t


def load_ticket(pool: Path, ticket_id: str) -> Ticket:
    return Ticket.load(_path(pool, ticket_id))


def save_ticket(pool: Path, ticket: Ticket) -> None:
    problems = ticket.validate()
    if problems:
        raise ValueError(f"工单校验失败: {problems}")
    ticket.save(_path(pool, ticket.id))
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/ticket.py tests/orchestrator/test_ticket.py
git commit -m "feat(orchestrator): 工单 schema 与 pool 存取"
```

---

### Task 5: 状态机 statemachine.py

**Files:**
- Create: `orchestrator/daemon/statemachine.py`
- Test: `tests/orchestrator/test_statemachine.py`

**Interfaces:**
- Consumes: `Ticket`(Task 4)、`append_event`(Task 3)
- Produces:
  - `TRANSITIONS: dict[str, dict[str, set[str]]]` — state → {next_state: 允许的 actor 集合}
  - `APPROVALS: dict[str, str]` — 老板审批点:当前状态 → 批准后目标状态
  - `transition(pool, ticket, to_state, actor, **ev) -> Ticket`(非法迁移/越权抛 `IllegalTransition`;成功则改 state、save、append state_changed 事件)
  - `suspend(pool, ticket, actor, reason) -> Ticket`(任意非终态 → suspended,记 resume_state)
  - `resume(pool, ticket, actor) -> Ticket`(suspended → resume_state)
  - `IllegalTransition` 异常类

迁移表(actor `"*"` = 任意):

```python
TRANSITIONS = {
    "draft":         {"p0_proposed": {"pm"}, "closed": {"boss"}},
    "p0_proposed":   {"p1_drafting": {"boss"}, "closed": {"boss"}},
    "p1_drafting":   {"p1_proposed": {"pm"}, "suspended": {"*"}},
    "p1_proposed":   {"p2_designing": {"boss"}, "closed": {"boss"}},
    "p2_designing":  {"p2_approved": {"boss"}, "p1_drafting": {"boss"}, "suspended": {"*"}},
    "p2_approved":   {"p3_queued": {"system"}},
    "p3_queued":     {"p3_running": {"system"}},
    "p3_running":    {"p4_verifying": {"system"}, "suspended": {"*"}},
    "p4_verifying":  {"p5_ready": {"qa"}, "p3_running": {"qa"}, "suspended": {"*"}},
    "p5_ready":      {"p5_releasing": {"boss"}, "suspended": {"*"}},
    "p5_releasing":  {"monitoring": {"release"}, "suspended": {"*"}},
    "monitoring":    {"done": {"sre"}, "suspended": {"*"}},
    "suspended":     {},  # 恢复走 resume()
    "done":          {},
    "closed":        {},
}

APPROVALS = {
    "p0_proposed": "p1_drafting",
    "p1_proposed": "p2_designing",
    "p2_designing": "p2_approved",
    "p5_ready": "p5_releasing",
}
```

- [ ] **Step 1: 写失败测试**

```python
import pytest
from orchestrator.daemon.statemachine import (
    APPROVALS, IllegalTransition, resume, suspend, transition,
)
from orchestrator.daemon.ticket import new_ticket
from orchestrator.daemon.events import read_events


def test_happy_path_boss_approves_p0(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, APPROVALS["p0_proposed"], actor="boss")
    assert t.state == "p1_drafting"
    events = read_events(pool, t.id)
    assert events[-1]["event"] == "state_changed"
    assert events[-1]["to"] == "p1_drafting"


def test_illegal_transition_rejected(pool):
    t = new_ticket(pool, project="p", summary="x")
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p3_running", actor="pm")


def test_wrong_actor_rejected(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p1_drafting", actor="pm")  # 审批是老板特权


def test_suspend_resume(pool):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    suspend(pool, t, actor="system", reason="熔断用尽")
    assert t.state == "suspended"
    assert t.resume_state == "p0_proposed"
    resume(pool, t, actor="boss")
    assert t.state == "p0_proposed"
    assert t.resume_state is None


def test_done_is_terminal(pool):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "done"
    with pytest.raises(IllegalTransition):
        transition(pool, t, "p0_proposed", actor="boss")
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""工单状态机。迁移即事件;审批门禁见 spec 第 2 节。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.daemon.events import append_event
from orchestrator.daemon.ticket import Ticket, save_ticket

TRANSITIONS = {
    "draft":         {"p0_proposed": {"pm"}, "closed": {"boss"}},
    "p0_proposed":   {"p1_drafting": {"boss"}, "closed": {"boss"}},
    "p1_drafting":   {"p1_proposed": {"pm"}, "suspended": {"*"}},
    "p1_proposed":   {"p2_designing": {"boss"}, "closed": {"boss"}},
    "p2_designing":  {"p2_approved": {"boss"}, "p1_drafting": {"boss"}, "suspended": {"*"}},
    "p2_approved":   {"p3_queued": {"system"}},
    "p3_queued":     {"p3_running": {"system"}},
    "p3_running":    {"p4_verifying": {"system"}, "suspended": {"*"}},
    "p4_verifying":  {"p5_ready": {"qa"}, "p3_running": {"qa"}, "suspended": {"*"}},
    "p5_ready":      {"p5_releasing": {"boss"}, "suspended": {"*"}},
    "p5_releasing":  {"monitoring": {"release"}, "suspended": {"*"}},
    "monitoring":    {"done": {"sre"}, "suspended": {"*"}},
    "suspended":     {},
    "done":          {},
    "closed":        {},
}

APPROVALS = {
    "p0_proposed": "p1_drafting",
    "p1_proposed": "p2_designing",
    "p2_designing": "p2_approved",
    "p5_ready": "p5_releasing",
}


class IllegalTransition(Exception):
    pass


def transition(pool: Path, ticket: Ticket, to_state: str, actor: str, **ev) -> Ticket:
    allowed = TRANSITIONS.get(ticket.state, {}).get(to_state)
    if allowed is None:
        raise IllegalTransition(f"{ticket.state} → {to_state} 不在迁移表")
    if "*" not in allowed and actor not in allowed:
        raise IllegalTransition(f"{ticket.state} → {to_state} 不允许 actor={actor}")
    frm = ticket.state
    ticket.state = to_state
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "state_changed", frm=frm, to=to_state, **ev)
    return ticket


def suspend(pool: Path, ticket: Ticket, actor: str, reason: str) -> Ticket:
    if ticket.state in {"done", "closed", "suspended"}:
        raise IllegalTransition(f"{ticket.state} 不可挂起")
    ticket.resume_state = ticket.state
    ticket.state = "suspended"
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "suspended",
                 resume_state=ticket.resume_state, reason=reason)
    return ticket


def resume(pool: Path, ticket: Ticket, actor: str) -> Ticket:
    if ticket.state != "suspended" or not ticket.resume_state:
        raise IllegalTransition("非挂起状态,无法恢复")
    target = ticket.resume_state
    ticket.state = target
    ticket.resume_state = None
    save_ticket(pool, ticket)
    append_event(pool, ticket.id, actor, "resumed", to=target)
    return ticket
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/statemachine.py tests/orchestrator/test_statemachine.py
git commit -m "feat(orchestrator): 工单状态机与审批门禁"
```

---

### Task 6: 适配器契约 + FakeHarness

**Files:**
- Create: `orchestrator/adapters/base.py`
- Create: `orchestrator/adapters/fake.py`
- Test: `tests/orchestrator/test_fake_adapter.py`

**Interfaces:**
- Produces:
  - `TaskPacket` dataclass:`role: str, prompt: str, workdir: Path, artifacts_in: list, artifacts_out: list, acceptance_cmd: str | None, budget: dict, timeout: int = 1800`
  - `HarnessResult` dataclass:`status: str(done|failed|timeout), output: str, tokens: dict, cost_cny: float, log_path: str | None`
  - `HarnessAdapter` 抽象基类:`name: str`、`run(packet: TaskPacket) -> HarnessResult`
  - `FakeHarness(script: list[str] | None = None)`:`run()` 按脚本依次返回 done/failed,脚本用尽后永远 done;`received: list[TaskPacket]` 记录收到的任务包

- [ ] **Step 1: 写失败测试**

```python
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.fake import FakeHarness


def _packet(tmp_path):
    return TaskPacket(role="dev", prompt="做任务", workdir=tmp_path,
                      artifacts_in=[], artifacts_out=[], acceptance_cmd=None,
                      budget={})


def test_fake_returns_scripted(tmp_path):
    h = FakeHarness(script=["failed", "done"])
    assert h.run(_packet(tmp_path)).status == "failed"
    assert h.run(_packet(tmp_path)).status == "done"
    assert h.run(_packet(tmp_path)).status == "done"  # 脚本用尽默认 done


def test_fake_records_packets(tmp_path):
    h = FakeHarness()
    p = _packet(tmp_path)
    h.run(p)
    assert h.received[0].prompt == "做任务"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

`orchestrator/adapters/base.py`:

```python
"""Harness 适配器契约。编排器与 CC/dsh 之间的唯一接触面。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskPacket:
    role: str
    prompt: str
    workdir: Path
    artifacts_in: list = field(default_factory=list)
    artifacts_out: list = field(default_factory=list)
    acceptance_cmd: str | None = None
    budget: dict = field(default_factory=dict)
    timeout: int = 1800


@dataclass
class HarnessResult:
    status: str            # done | failed | timeout
    output: str = ""
    tokens: dict = field(default_factory=dict)
    cost_cny: float = 0.0
    log_path: str | None = None


class HarnessAdapter(ABC):
    name: str

    @abstractmethod
    def run(self, packet: TaskPacket) -> HarnessResult:
        ...
```

`orchestrator/adapters/fake.py`:

```python
"""测试用假 harness:按脚本返回,不调用任何真实模型。"""
from __future__ import annotations

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class FakeHarness(HarnessAdapter):
    name = "fake"

    def __init__(self, script: list[str] | None = None):
        self._script = list(script or [])
        self.received: list[TaskPacket] = []

    def run(self, packet: TaskPacket) -> HarnessResult:
        self.received.append(packet)
        status = self._script.pop(0) if self._script else "done"
        return HarnessResult(status=status, output=f"fake:{packet.role}:{status}")
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/adapters/ tests/orchestrator/test_fake_adapter.py
git commit -m "feat(orchestrator): 适配器契约 + FakeHarness"
```

---

### Task 7: 执行器 runner.py

**Files:**
- Create: `orchestrator/daemon/runner.py`
- Test: `tests/orchestrator/test_runner.py`

**Interfaces:**
- Consumes: `Ticket/load_ticket/save_ticket`、`transition`、`append_event`、`HarnessAdapter/TaskPacket/HarnessResult`
- Produces:
  - `WORK_STATES: dict[str, str]` — 需要 harness 干活的状态 → 角色:`{"p1_drafting": "pm", "p2_designing": "architect", "p3_running": "dev", "p4_verifying": "qa", "p5_releasing": "release", "monitoring": "sre"}`
  - `advance_once(pool, ticket_id, adapter, project_dir) -> str` — 对当前状态推进一步,返回动作描述。规则:
    - 系统态(`p2_approved→p3_queued→p3_running`)自动连续迁移,返回 `"auto: p3_running"`
    - WORK_STATES 中的状态:构造 TaskPacket(prompt 含工单 summary,workdir=project_dir),调 adapter,追加 `role_run` 事件(含 result.status/tokens);成功按 `SUCCESS_NEXT = {"p1_drafting": "p1_proposed", "p3_running": "p4_verifying", "p4_verifying": "p5_ready", "p5_releasing": "monitoring", "monitoring": "done"}` 迁移(`p2_designing` 成功后**停留原状态**等老板审批,仅更新 owner_role=boss);失败则 `suspend(reason=f"{role} 执行失败")`(熔断阶梯在 M3 细化)
    - 其他状态(等审批/终态)返回 `"idle: <state>"`

- [ ] **Step 1: 写失败测试**

```python
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import transition
from orchestrator.daemon.ticket import load_ticket, new_ticket
from orchestrator.daemon.events import read_events


def test_pm_drafts_prd(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="加缓存")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    msg = advance_once(pool, t.id, FakeHarness(), tmp_path)
    assert msg.startswith("role:pm")
    assert load_ticket(pool, t.id).state == "p1_proposed"


def test_system_states_auto_advance(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p2_approved"
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    msg = advance_once(pool, t.id, FakeHarness(), tmp_path)
    assert load_ticket(pool, t.id).state == "p3_running"
    assert "p3_running" in msg


def test_failure_suspends(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    advance_once(pool, t.id, FakeHarness(script=["failed"]), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    assert t2.resume_state == "p1_drafting"
    assert any(e["event"] == "role_run" and e["status"] == "failed"
               for e in read_events(pool, t.id))


def test_architect_stays_for_approval(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p2_designing"
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "p2_designing"
    assert t2.owner_role == "boss"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""执行器:对工单当前状态推进一步。M1 形态:同步单步;常驻循环在 M3+。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, TaskPacket
from orchestrator.daemon.events import append_event
from orchestrator.daemon.statemachine import suspend, transition
from orchestrator.daemon.ticket import load_ticket, save_ticket

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


def advance_once(pool: Path, ticket_id: str, adapter: HarnessAdapter,
                 project_dir: Path) -> str:
    t = load_ticket(pool, ticket_id)

    if t.state in SYSTEM_NEXT:
        while t.state in SYSTEM_NEXT:
            transition(pool, t, SYSTEM_NEXT[t.state], actor="system")
        return f"auto: {t.state}"

    role = WORK_STATES.get(t.state)
    if role is None:
        return f"idle: {t.state}"

    packet = TaskPacket(
        role=role,
        prompt=f"[{role}] 工单 {t.id}: {t.summary}",
        workdir=project_dir,
        budget=t.budget,
    )
    result = adapter.run(packet)
    append_event(pool, t.id, role, "role_run",
                 status=result.status, tokens=result.tokens,
                 cost_cny=result.cost_cny, output=result.output[:500])

    if result.status == "done":
        if t.state == "p2_designing":
            t.owner_role = "boss"
            save_ticket(pool, t)
        else:
            transition(pool, t, SUCCESS_NEXT[t.state], actor="system" if t.state == "p3_running" else role)
    else:
        suspend(pool, t, actor="system", reason=f"{role} 执行失败: {result.status}")
    return f"role:{role}:{result.status}"
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/runner.py tests/orchestrator/test_runner.py
git commit -m "feat(orchestrator): 执行器 advance_once"
```

---

### Task 8: CLI orc

**Files:**
- Create: `orchestrator/daemon/cli.py`
- Test: `tests/orchestrator/test_cli.py`

**Interfaces:**
- Consumes: ticket/statemachine/runner 全部接口
- Produces: `main(argv: list[str] | None = None) -> int`,命令:
  - `orc new <project> <summary> [--by probe]`
  - `orc list`(按状态分组列出工单)
  - `orc show <id>`(工单详情 + 事件流)
  - `orc approve <id>`(= `transition(t, APPROVALS[t.state], "boss")`,非审批态报错)
  - `orc reject <id>`(→ closed)
  - `orc suspend <id> <reason>` / `orc resume <id>`
  - `orc advance <id> <project_dir> [--fake]`(调 advance_once;`--fake` 用 FakeHarness,否则按角色路由——M2 Task 14 接真 adapter,M1 只实现 --fake 分支,无 --fake 时报错"真实适配器未接入")
  - pool 路径:读 `orchestrator.yaml` 的 `pool` 字段(相对仓库根)

- [ ] **Step 1: 写失败测试**

```python
import yaml
from pathlib import Path
from orchestrator.daemon.cli import main


def _cfg(tmp_path, monkeypatch):
    (tmp_path / "orchestrator.yaml").write_text(
        yaml.safe_dump({"pool": "pool", "projects": {}, "thresholds": {"concurrent_max": 2}}),
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def test_new_list_approve(tmp_path, monkeypatch, capsys):
    _cfg(tmp_path, monkeypatch)
    assert main(["new", "quant-lab", "加缓存"]) == 0
    out = capsys.readouterr().out
    tid = [w for w in out.split() if w.startswith("T-")][0]

    assert main(["advance", tid, ".", "--fake"]) == 0          # draft→p0_proposed? 否:draft 是 idle
    # draft 需要先由 pm 提交:用 advance 让 pm 干活?draft 不在 WORK_STATES。
    # 设计决策:orc new 后直接 pm 提交走 approve 前需要 p0_proposed。
    # 简化:new 之后提供 submit 动作由 advance 处理 draft 状态。
    assert main(["approve", tid, "--as", "pm"]) == 0            # pm 提交 draft→p0_proposed
    assert main(["approve", tid]) == 0                          # boss:p0→p1
    assert main(["advance", tid, ".", "--fake"]) == 0           # pm 写 PRD→p1_proposed
    assert main(["approve", tid]) == 0                          # boss:p1→p2
    assert main(["advance", tid, ".", "--fake"]) == 0           # architect→等审批
    assert main(["approve", tid]) == 0                          # boss:p2_approved
    assert main(["advance", tid, ".", "--fake"]) == 0           # auto→p3_running? auto 只迁移系统态
    assert main(["advance", tid, ".", "--fake"]) == 0           # dev→p4
    assert main(["advance", tid, ".", "--fake"]) == 0           # qa→p5_ready
    assert main(["approve", tid]) == 0                          # boss:p5_releasing
    assert main(["advance", tid, ".", "--fake"]) == 0           # release→monitoring
    assert main(["advance", tid, ".", "--fake"]) == 0           # sre→done
    assert main(["show", tid]) == 0
    out = capsys.readouterr().out
    assert "done" in out
    assert "state_changed" in out
```

设计说明(实现时照此):`orc approve <id>` 在无 `--as` 时按老板审批走 APPROVALS;`--as pm` 处理 `draft→p0_proposed`(PM 提交草稿)。advance 的 auto 分支一次调用只迁移一段系统态链(Task 7 的 while 已实现 p2_approved→p3_running 一跳到底),所以上面 p2_approved 后第一次 advance 到 p3_running,第二次 dev 干活。

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""orc 命令行:老板与编排器交互的入口。审批=改状态,git 留痕。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import (
    APPROVALS, IllegalTransition, resume, suspend, transition,
)
from orchestrator.daemon.ticket import load_ticket, new_ticket


def _pool() -> Path:
    cfg = yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))
    return Path(cfg["pool"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orc")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("new"); c.add_argument("project"); c.add_argument("summary"); c.add_argument("--by", default="human")
    sub.add_parser("list")
    c = sub.add_parser("show"); c.add_argument("id")
    c = sub.add_parser("approve"); c.add_argument("id"); c.add_argument("--as", dest="actor", default="boss")
    c = sub.add_parser("reject"); c.add_argument("id")
    c = sub.add_parser("suspend"); c.add_argument("id"); c.add_argument("reason")
    c = sub.add_parser("resume"); c.add_argument("id")
    c = sub.add_parser("advance"); c.add_argument("id"); c.add_argument("project_dir"); c.add_argument("--fake", action="store_true")
    args = p.parse_args(argv)
    pool = _pool()

    try:
        if args.cmd == "new":
            t = new_ticket(pool, args.project, args.summary, created_by=args.by)
            print(f"created {t.id} (draft)")
        elif args.cmd == "list":
            for f in sorted((pool / "tickets").glob("*.yaml")):
                t = load_ticket(pool, f.stem)
                print(f"{t.id}  [{t.state}]  {t.project}  {t.summary}")
        elif args.cmd == "show":
            t = load_ticket(pool, args.id)
            print(f"{t.id} [{t.state}] owner={t.owner_role} project={t.project}\n{ t.summary}")
            for e in read_events(pool, args.id):
                print(f"  {e['ts'][:19]}  {e['actor']:<10} {e['event']}")
        elif args.cmd == "approve":
            t = load_ticket(pool, args.id)
            if args.actor == "pm" and t.state == "draft":
                transition(pool, t, "p0_proposed", actor="pm")
            else:
                target = APPROVALS.get(t.state)
                if not target:
                    print(f"{t.state} 不是审批态", file=sys.stderr)
                    return 1
                transition(pool, t, target, actor=args.actor)
            print(f"{args.id} → {load_ticket(pool, args.id).state}")
        elif args.cmd == "reject":
            transition(pool, load_ticket(pool, args.id), "closed", actor="boss")
            print(f"{args.id} → closed")
        elif args.cmd == "suspend":
            suspend(pool, load_ticket(pool, args.id), actor="boss", reason=args.reason)
            print(f"{args.id} → suspended")
        elif args.cmd == "resume":
            resume(pool, load_ticket(pool, args.id), actor="boss")
            print(f"{args.id} → resumed")
        elif args.cmd == "advance":
            if not args.fake:
                print("真实适配器未接入(M2),请用 --fake", file=sys.stderr)
                return 1
            print(advance_once(pool, args.id, FakeHarness(), Path(args.project_dir)))
    except (IllegalTransition, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 1 passed(长链路全过)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/cli.py tests/orchestrator/test_cli.py
git commit -m "feat(orchestrator): orc CLI(new/list/show/approve/advance)"
```

---

### Task 9: M1 验收 —— 全链路 e2e + 推送

**Files:**
- Test: `tests/orchestrator/test_e2e_fake.py`

**Interfaces:**
- Consumes: Task 1-8 全部
- Produces: M1 验收证据(假工单 draft→done,事件日志完整)

- [ ] **Step 1: 写验收测试(直接调库,不走 CLI,断言事件序列)**

```python
"""M1 验收:一张假工单从 draft 走到 done,事件日志完整。"""
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import APPROVALS, transition
from orchestrator.daemon.ticket import load_ticket, new_ticket


def test_full_lifecycle_with_fake_harness(pool, tmp_path):
    h = FakeHarness()
    t = new_ticket(pool, project="quant-lab", summary="给报表加缓存", created_by="probe")

    transition(pool, t, "p0_proposed", actor="pm")
    for state in ["p0_proposed", "p1_proposed"]:
        transition(pool, load_ticket(pool, t.id), APPROVALS[state], actor="boss")
        advance_once(pool, t.id, h, tmp_path)
    # p2: architect 干完后老板批
    transition(pool, load_ticket(pool, t.id), "p2_approved", actor="boss")
    advance_once(pool, t.id, h, tmp_path)   # auto→p3_running
    advance_once(pool, t.id, h, tmp_path)   # dev→p4
    advance_once(pool, t.id, h, tmp_path)   # qa→p5_ready
    transition(pool, load_ticket(pool, t.id), "p5_releasing", actor="boss")
    advance_once(pool, t.id, h, tmp_path)   # release→monitoring
    advance_once(pool, t.id, h, tmp_path)   # sre→done

    assert load_ticket(pool, t.id).state == "done"
    kinds = [e["event"] for e in read_events(pool, t.id)]
    assert kinds[0] == "created"
    assert "state_changed" in kinds and "role_run" in kinds
    roles = [e["actor"] for e in read_events(pool, t.id) if e["event"] == "role_run"]
    assert roles == ["pm", "architect", "dev", "qa", "release", "sre"]
```

- [ ] **Step 2: 跑全套测试**

```bash
python -m pytest tests/orchestrator/ -v
```

Expected: 全 passed(含本 e2e)

- [ ] **Step 3: Commit + push(M1 完成)**

```bash
git add tests/orchestrator/test_e2e_fake.py
git commit -m "test(orchestrator): M1 验收 —— FakeHarness 全生命周期 e2e"
git push
```

---

### Task 10: Worktree 池

**Files:**
- Create: `orchestrator/daemon/worktree.py`
- Test: `tests/orchestrator/test_worktree.py`

**Interfaces:**
- Produces:
  - `ensure_worktree(project: Path, name: str, base: str = "main") -> Path` — 在 `<project>/.orc-worktrees/<name>` 创建(或复用已存在的)git worktree
  - `recycle_worktree(project: Path, name: str) -> None` — `git worktree remove --force`
  - `list_worktrees(project: Path) -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
import subprocess
from pathlib import Path
import pytest
from orchestrator.daemon.worktree import ensure_worktree, list_worktrees, recycle_worktree


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "README.md").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=r, check=True, capture_output=True)
    return r


def test_ensure_and_recycle(repo):
    wt = ensure_worktree(repo, "task-1")
    assert wt.exists()
    assert (wt / "README.md").exists()
    assert "task-1" in list_worktrees(repo)
    # 复用:不报错,路径相同
    assert ensure_worktree(repo, "task-1") == wt
    recycle_worktree(repo, "task-1")
    assert "task-1" not in list_worktrees(repo)
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""开发角色的工位:每任务一个 git worktree,崩了最多损失一个。"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(project: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def ensure_worktree(project: Path, name: str, base: str = "main") -> Path:
    wt = project / ".orc-worktrees" / name
    if wt.exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(project, "worktree", "add", str(wt), "-b", f"orc/{name}", base)
    return wt


def list_worktrees(project: Path) -> list[str]:
    root = project / ".orc-worktrees"
    if not root.exists():
        return []
    return [p.name for p in root.iterdir() if p.is_dir()]


def recycle_worktree(project: Path, name: str) -> None:
    _git(project, "worktree", "remove", "--force", str(project / ".orc-worktrees" / name))
    _git(project, "branch", "-D", f"orc/{name}")
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/worktree.py tests/orchestrator/test_worktree.py
git commit -m "feat(orchestrator): worktree 池"
```

---

### Task 11: 任务切片 slicer.py

**Files:**
- Create: `orchestrator/daemon/slicer.py`
- Create: `plugin/templates/tasks.template.yaml`(任务清单模板,P2 产物之一)
- Test: `tests/orchestrator/test_slicer.py`

**Interfaces:**
- Consumes: `TaskPacket`
- Produces:
  - 任务清单契约:P2 设计产物附带 `docs/specs/<ticket>-tasks.yaml`,schema:`[{id, title, acceptance_cmd, depends_on: []}]`
  - `load_task_list(path: Path) -> list[dict]`(校验 id 唯一、depends_on 引用存在)
  - `ready_tasks(tasks: list[dict]) -> list[dict]`(status==pending 且 depends_on 全部 done)
  - `make_packet(task: dict, ticket, workdir: Path, design_excerpt: str) -> TaskPacket`(role=dev,prompt 含 TDD 强制指令)
  - TDD 指令模板(写死):`"严格遵守 TDD:先写失败的测试,再实现,再运行 {acceptance_cmd} 直至通过。"`

- [ ] **Step 1: 写失败测试**

```python
import pytest
from orchestrator.daemon.slicer import load_task_list, make_packet, ready_tasks
from orchestrator.daemon.ticket import new_ticket


def test_load_and_validate(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text(
        "- id: task-1\n  title: 建模型\n  acceptance_cmd: pytest -x\n  depends_on: []\n"
        "- id: task-2\n  title: 写接口\n  acceptance_cmd: pytest\n  depends_on: [task-1]\n",
        encoding="utf-8")
    tasks = load_task_list(f)
    assert [t["id"] for t in tasks] == ["task-1", "task-2"]
    assert tasks[0]["status"] == "pending"


def test_ready_respects_dependencies(tmp_path):
    tasks = [
        {"id": "task-1", "status": "pending", "depends_on": []},
        {"id": "task-2", "status": "pending", "depends_on": ["task-1"]},
    ]
    assert [t["id"] for t in ready_tasks(tasks)] == ["task-1"]
    tasks[0]["status"] = "done"
    assert [t["id"] for t in ready_tasks(tasks)] == ["task-2"]


def test_bad_dependency_rejected(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text("- id: task-1\n  title: x\n  acceptance_cmd: c\n  depends_on: [ghost]\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="ghost"):
        load_task_list(f)


def test_make_packet_has_tdd(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    pkt = make_packet({"id": "task-1", "title": "建模型", "acceptance_cmd": "pytest -x",
                       "depends_on": []}, t, tmp_path, "设计节选")
    assert pkt.role == "dev"
    assert "TDD" in pkt.prompt and "pytest -x" in pkt.prompt
    assert pkt.workdir == tmp_path
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""任务切片:P2 设计产物 → 可派发的任务包。"""
from __future__ import annotations

from pathlib import Path

import yaml

from orchestrator.adapters.base import TaskPacket

TDD_INSTRUCTION = (
    "严格遵守 TDD:先写一个失败的测试,再写最小实现让它通过,"
    "然后运行验收命令 `{cmd}` 直至退出码为 0。不许先写实现。"
)


def load_task_list(path: Path) -> list[dict]:
    tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("任务 id 重复")
    for t in tasks:
        t.setdefault("status", "pending")
        t.setdefault("attempts", 0)
        for dep in t.get("depends_on", []):
            if dep not in ids:
                raise ValueError(f"未知依赖: {dep}")
    return tasks


def ready_tasks(tasks: list[dict]) -> list[dict]:
    done = {t["id"] for t in tasks if t["status"] == "done"}
    return [t for t in tasks
            if t["status"] == "pending" and set(t.get("depends_on", [])) <= done]


def make_packet(task: dict, ticket, workdir: Path, design_excerpt: str) -> TaskPacket:
    prompt = (
        f"你是开发角色,在 git worktree 中独立完成任务 {task['id']}: {task['title']}\n"
        f"工单: {ticket.id} — {ticket.summary}\n"
        f"设计节选:\n{design_excerpt}\n\n"
        + TDD_INSTRUCTION.format(cmd=task["acceptance_cmd"])
    )
    return TaskPacket(role="dev", prompt=prompt, workdir=workdir,
                      acceptance_cmd=task["acceptance_cmd"], budget=ticket.budget)
```

`plugin/templates/tasks.template.yaml`:

```yaml
# P2 设计产物附件:任务切片清单。契约见 orchestrator/daemon/slicer.py
- id: task-1
  title: "{{TASK_TITLE}}"
  acceptance_cmd: "{{ACCEPTANCE_CMD}}"   # 如 "python -m pytest tests/ -x"
  depends_on: []
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/daemon/slicer.py plugin/templates/tasks.template.yaml tests/orchestrator/test_slicer.py
git commit -m "feat(orchestrator): 任务切片与 TDD 任务包"
```

---

### Task 12: Claude Code 适配器

**Files:**
- Create: `orchestrator/adapters/claude_code.py`
- Test: `tests/orchestrator/test_claude_code_adapter.py`(单测 mock subprocess;真实调用在 Task 15 的 slow 测试)

**Interfaces:**
- Consumes: `HarnessAdapter/TaskPacket/HarnessResult`
- Produces: `ClaudeCodeAdapter(HarnessAdapter)`,`name = "claude_code"`;`run(packet)`:
  - 命令:`claude -p <prompt> --output-format json`(cwd=packet.workdir,timeout=packet.timeout)
  - 解析 stdout JSON:取 `result` 文本与 `usage`(若有)填 tokens;`is_error` 或 returncode≠0 → failed;`subprocess.TimeoutExpired` → timeout
  -  stdout 落盘 `pool/logs/<ticket>/`(由 runner 负责,适配器只返回 output)

- [ ] **Step 1: 写失败测试(mock subprocess.run)**

```python
import json
import subprocess
from unittest.mock import patch
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.claude_code import ClaudeCodeAdapter


def _packet(tmp_path):
    return TaskPacket(role="pm", prompt="写 PRD", workdir=tmp_path, budget={})


def test_success_parses_json(tmp_path):
    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({"result": "PRD 已写", "is_error": False,
                           "usage": {"input_tokens": 100, "output_tokens": 50}}),
        stderr="")
    with patch("subprocess.run", return_value=fake):
        r = ClaudeCodeAdapter().run(_packet(tmp_path))
    assert r.status == "done"
    assert r.output == "PRD 已写"
    assert r.tokens == {"input_tokens": 100, "output_tokens": 50}


def test_nonzero_exit_is_failed(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="boom", stderr="")
    with patch("subprocess.run", return_value=fake):
        assert ClaudeCodeAdapter().run(_packet(tmp_path)).status == "failed"


def test_timeout(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1)):
        assert ClaudeCodeAdapter().run(_packet(tmp_path)).status == "timeout"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""Claude Code headless 适配器(k3 角色:PM/架构师/测试设计师/视觉 QA/会诊)。"""
from __future__ import annotations

import json
import subprocess

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class ClaudeCodeAdapter(HarnessAdapter):
    name = "claude_code"

    def run(self, packet: TaskPacket) -> HarnessResult:
        cmd = ["claude", "-p", packet.prompt, "--output-format", "json"]
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True,
                               text=True, timeout=packet.timeout)
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        if r.returncode != 0:
            return HarnessResult(status="failed", output=(r.stdout + r.stderr)[:2000])
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return HarnessResult(status="done", output=r.stdout)
        status = "failed" if data.get("is_error") else "done"
        return HarnessResult(status=status,
                             output=str(data.get("result", "")),
                             tokens=data.get("usage", {}))
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/adapters/claude_code.py tests/orchestrator/test_claude_code_adapter.py
git commit -m "feat(orchestrator): Claude Code headless 适配器"
```

---

### Task 13: dsh 适配器

**Files:**
- Create: `orchestrator/adapters/dsh.py`
- Test: `tests/orchestrator/test_dsh_adapter.py`(mock subprocess)

**Interfaces:**
- Produces: `DshAdapter(HarnessAdapter)`,`name = "dsh"`;`run(packet)`:
  - 命令:`dsh --profile headless <prompt>`(cwd=workdir,timeout)
  - 退出码 0 → done,非 0 → failed,TimeoutExpired → timeout;stdout+stderr 合并为 output
  - token/成本:dsh 输出若含 usage 行则解析(M2 先不解析,tokens={},cost=0;M3 台账再补)

- [ ] **Step 1: 写失败测试**

```python
import subprocess
from unittest.mock import patch, call
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import DshAdapter


def _packet(tmp_path):
    return TaskPacket(role="dev", prompt="实现 task-1", workdir=tmp_path, budget={})


def test_exit_zero_is_done(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake) as m:
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "done"
    assert m.call_args[0][0][:3] == ["dsh", "--profile", "headless"]


def test_nonzero_is_failed(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")
    with patch("subprocess.run", return_value=fake):
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "failed" and "err" in r.output


def test_timeout(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="dsh", timeout=1)):
        assert DshAdapter().run(_packet(tmp_path)).status == "timeout"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

```python
"""dsh headless 适配器(DeepSeek 角色:开发/脚本级 QA/发布员/SRE 巡检)。"""
from __future__ import annotations

import subprocess

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class DshAdapter(HarnessAdapter):
    name = "dsh"

    def run(self, packet: TaskPacket) -> HarnessResult:
        cmd = ["dsh", "--profile", "headless", packet.prompt]
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True,
                               text=True, timeout=packet.timeout)
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        output = (r.stdout + r.stderr)[:4000]
        return HarnessResult(status="done" if r.returncode == 0 else "failed",
                             output=output)
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add orchestrator/adapters/dsh.py tests/orchestrator/test_dsh_adapter.py
git commit -m "feat(orchestrator): dsh headless 适配器"
```

---

### Task 14: 角色路由 + runner 接入真实 adapter + worktree 派发

**Files:**
- Create: `orchestrator/adapters/__init__.py` 中提供 `get_adapter(name)`(替换空文件)
- Create: `orchestrator/roles/prompts/pm.md`、`architect.md`、`dev.md`、`qa.md`、`release.md`、`sre.md`
- Modify: `orchestrator/daemon/runner.py`(p3_running 分支:读工单 tasks,取 ready_tasks,逐任务建 worktree 派发;其余状态走角色 prompt 文件)
- Modify: `orchestrator/daemon/cli.py`(advance 去掉"未接入"报错,接 get_adapter)
- Test: `tests/orchestrator/test_routing.py`

**Interfaces:**
- Produces:
  - `ROLE_ROUTING = {"pm": "claude_code", "architect": "claude_code", "test_designer": "claude_code", "qa_vision": "claude_code", "dev": "dsh", "qa": "dsh", "release": "dsh", "sre": "dsh"}`
  - `get_adapter(name: str) -> HarnessAdapter`(`"fake"` 也支持,测试用)
  - runner 升级:`advance_once(pool, ticket_id, adapter, project_dir)` 签名不变;新增 `run_dev_tasks(pool, ticket, adapter, project_dir) -> str` 供 p3_running 调用

角色 prompt 文件内容(每个都是完整可用的最小人设):

`pm.md`:
```markdown
你是产品经理。基于工单摘要起草 PRD,写入当前项目 document/business/<工单号>-prd.md。
只写需求与验收标准,不讨论实现。输出格式遵循项目 PRD 模板。
```

`architect.md`:
```markdown
你是架构师。读 PRD 后产出设计文档(docs/specs/<工单号>-design.md)与任务切片清单
(docs/specs/<工单号>-tasks.yaml,契约:[{id,title,acceptance_cmd,depends_on}])。
切片原则:每任务独立可验收,上下文自包含。不写实现代码。
```

`dev.md`:
```markdown
你是开发。严格 TDD:先失败测试,再最小实现,再跑验收命令直至退出码 0。
只改动当前 worktree 内与任务相关的文件,完成时更新项目 backlog.md 对应条目。
```

`qa.md`:
```markdown
你是测试执行。按 docs/specs/ 下的黑盒计划逐条执行验收命令与 Playwright 脚本,
输出验收报告(每条用例:通过/失败/证据)。不看实现代码,不改任何源文件。
```

`release.md`:
```markdown
你是发布员。把工单的集成分支合并到 main 并打 tag。合并前跑全量测试命令,
失败则中止并报告。你是唯一能合 main 的角色。
```

`sre.md`:
```markdown
你是运维。执行 stack-profile.yaml blackbox 段定义的健康检查,全部通过则报告健康;
异常则执行预定义回滚命令并报告。不做检查清单之外的任何操作。
```

- [ ] **Step 1: 写失败测试(路由 + p3 任务派发,fake 跑通)**

```python
from orchestrator.adapters import get_adapter
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.runner import ROLE_ROUTING, advance_once
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket
import subprocess


def _git_repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=r, check=True, capture_output=True)
    return r


def test_routing():
    assert ROLE_ROUTING["dev"] == "dsh"
    assert ROLE_ROUTING["pm"] == "claude_code"
    assert isinstance(get_adapter("fake"), FakeHarness)


def test_p3_dispatches_ready_tasks(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": "task-1", "title": "a", "acceptance_cmd": "true", "depends_on": [],
         "status": "pending", "attempts": 0},
        {"id": "task-2", "title": "b", "acceptance_cmd": "true", "depends_on": ["task-1"],
         "status": "pending", "attempts": 0},
    ]
    save_ticket(pool, t)
    h = FakeHarness()
    msg = advance_once(pool, t.id, h, proj)
    t2 = load_ticket(pool, t.id)
    # 一次 advance 只派一个 ready 任务;task-2 依赖未满足
    assert t2.tasks[0]["status"] == "done"
    assert t2.tasks[1]["status"] == "pending"
    assert t2.state == "p3_running"
    # 任务包发到了该任务的 worktree
    assert "orc-task-1" in str(h.received[0].workdir) or "task-1" in str(h.received[0].workdir)
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL

- [ ] **Step 3: 实现**

`orchestrator/adapters/__init__.py`:

```python
from orchestrator.adapters.base import HarnessAdapter
from orchestrator.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.adapters.dsh import DshAdapter
from orchestrator.adapters.fake import FakeHarness

_REGISTRY = {
    "claude_code": ClaudeCodeAdapter,
    "dsh": DshAdapter,
    "fake": FakeHarness,
}


def get_adapter(name: str) -> HarnessAdapter:
    return _REGISTRY[name]()
```

runner.py 修改:p3_running 分支替换为调用 `run_dev_tasks`(新增):

```python
from orchestrator.daemon.slicer import make_packet, ready_tasks
from orchestrator.daemon.worktree import ensure_worktree

ROLE_ROUTING = {
    "pm": "claude_code", "architect": "claude_code", "test_designer": "claude_code",
    "qa_vision": "claude_code", "dev": "dsh", "qa": "dsh",
    "release": "dsh", "sre": "dsh",
}


def run_dev_tasks(pool, ticket, adapter, project_dir) -> str:
    ready = ready_tasks(ticket.tasks)
    if not ready:
        if all(t["status"] == "done" for t in ticket.tasks):
            transition(pool, ticket, "p4_verifying", actor="system")
            return "auto: p4_verifying"
        return "idle: p3_running(no ready tasks)"
    task = ready[0]
    wt = ensure_worktree(project_dir, task["id"])
    packet = make_packet(task, ticket, wt, design_excerpt="")
    result = adapter.run(packet)
    task["attempts"] += 1
    append_event(pool, ticket.id, "dev", "task_run", task=task["id"],
                 attempt=task["attempts"], status=result.status,
                 tokens=result.tokens, cost_cny=result.cost_cny)
    if result.status == "done":
        task["status"] = "done"
        save_ticket(pool, ticket)
    else:
        save_ticket(pool, ticket)  # attempts 已记;熔断阶梯 M3 接管
        suspend(pool, ticket, actor="system",
                reason=f"任务 {task['id']} 第 {task['attempts']} 次失败")
    return f"task:{task['id']}:{result.status}"
```

advance_once 的 p3_running 分支改为 `return run_dev_tasks(pool, t, adapter, project_dir)`;非 p3 的 WORK_STATES 分支在构造 prompt 时读角色 prompt 文件:`(Path(__file__).parent.parent / "roles" / "prompts" / f"{role}.md").read_text(encoding="utf-8")` 作为 prompt 前缀。

cli.py:`advance` 分支改为:

```python
adapter = FakeHarness() if args.fake else get_adapter(ROLE_ROUTING.get(
    WORK_STATES.get(load_ticket(pool, args.id).state, "dev"), "dsh"))
print(advance_once(pool, args.id, adapter, Path(args.project_dir)))
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest tests/orchestrator/ -v
```

Expected: 全 passed(旧 runner 测试不受影响:它们用的是 p1/p2 等非 p3 状态或 fake)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/ tests/orchestrator/test_routing.py
git commit -m "feat(orchestrator): 角色路由 + p3 任务级 worktree 派发"
```

---

### Task 15: M2 验收 —— 真实 harness 集成验证(slow)

**Files:**
- Test: `tests/orchestrator/test_integration_live.py`
- Create: `d:\workspace\tmp\orc-e2e\`(验收用临时项目,不入库)

**Interfaces:**
- Consumes: 全部
- Produces: M2 验收证据:真实 `claude -p` 与真实 `dsh --profile headless` 各完成一次最小任务

- [ ] **Step 1: 写 slow 集成测试**

```python
import shutil
import pytest
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.adapters.dsh import DshAdapter

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not shutil.which("claude"), reason="无 claude CLI")
def test_claude_headless_minimal(tmp_path):
    pkt = TaskPacket(role="pm", prompt="用一句话回答:1+1等于几?只输出数字。",
                     workdir=tmp_path, budget={}, timeout=300)
    r = ClaudeCodeAdapter().run(pkt)
    assert r.status == "done"
    assert "2" in r.output


@pytest.mark.skipif(not shutil.which("dsh"), reason="无 dsh CLI")
def test_dsh_headless_minimal(tmp_path):
    pkt = TaskPacket(role="dev", prompt="用一句话回答:1+1等于几?只输出数字。",
                     workdir=tmp_path, budget={}, timeout=300)
    r = DshAdapter().run(pkt)
    assert r.status == "done"
    assert "2" in r.output
```

`tests/orchestrator/conftest.py` 追加 slow 标记支持(`pytest.ini` 或 conftest):

```python
def pytest_collection_modifyitems(config, items):
    import pytest
    if config.getoption("-m") and "slow" in config.getoption("-m"):
        return
    skip = pytest.mark.skip(reason="slow,用 -m slow 显式运行")
    for item in items:
        if "slow" in item.keywords and "-m" not in str(config.invocation_params.args):
            item.add_marker(skip)
```

(若行为不符合预期,退而用 `pytest.ini` 注册 marker + 手动 `pytest -m slow`;记录实际做法)

- [ ] **Step 2: 跑 slow 测试(两个 CLI 都真实调用)**

```bash
python -m pytest tests/orchestrator/test_integration_live.py -v -m slow
```

Expected: 2 passed。**若 claude -p 卡在权限提示**:这是 spec 风险 #2,记录现象,在 `d:\workspace\tmp\orc-e2e\.claude\settings.json` 配权限白名单后重试,并把结论追加到 spec 风险清单。

- [ ] **Step 3: 真实小工单手工验收(与用户一起)**

在 `d:\workspace\tmp\orc-e2e\` 用 ai-init 初始化一个 scratch 项目,手工走:

```bash
cd d:/workspace/ai-factory
python -m orchestrator.daemon.cli new orc-e2e "实现一个 add(a,b) 函数并带测试"
python -m orchestrator.daemon.cli approve <id> --as pm
python -m orchestrator.daemon.cli approve <id>          # P0
python -m orchestrator.daemon.cli advance <id> d:/workspace/tmp/orc-e2e   # PM(k3)写 PRD
python -m orchestrator.daemon.cli approve <id>          # P1
python -m orchestrator.daemon.cli advance <id> d:/workspace/tmp/orc-e2e   # 架构师(k3)设计+切片
python -m orchestrator.daemon.cli approve <id>          # P2
python -m orchestrator.daemon.cli advance <id> d:/workspace/tmp/orc-e2e   # →p3_running
python -m orchestrator.daemon.cli advance <id> d:/workspace/tmp/orc-e2e   # dev(dsh)任务1…直至 p4
python -m orchestrator.daemon.cli show <id>             # 检查事件流
```

验收标准:PM/架构师产物落在 orc-e2e 项目内;dsh 在 worktree 里 TDD 出 add 函数且验收命令通过;事件日志含全部 role_run/task_run 记录。

- [ ] **Step 4: Commit + push(M2 完成)**

```bash
git add tests/orchestrator/
git commit -m "test(orchestrator): M2 验收 —— 真实双 harness 集成(slow)"
git push
```

---

## Self-Review 记录

- **Spec 覆盖**:M1=状态机(§2)+适配器契约(§3 FakeHarness 部分)+测试策略(§7.1 单测/契约测试);M2=CC/dsh 适配器(§3)+worktree 池(§6.2)+任务切片(§3 任务包)。探针(§4)、熔断细化+台账(§5)、dashboard 属 M3-M5,不在本计划 —— 与 spec 里程碑表一致。
- **类型一致性**:`TaskPacket/HarnessResult/advance_once/get_adapter/ROLE_ROUTING/ready_tasks/make_packet/ensure_worktree` 在 Task 6-14 间签名一致;`orc approve --as pm` 的 draft→p0_proposed 语义在 Task 8 测试与实现一致。
- **已知留白(有意)**:p2_designing 的测试设计师出题(§1 名册)在 M2 由架构师一并完成,角色拆分随 M5 探针一起做;qa 的视觉级路由(k3-vision)待 M4+。这些不影响 M1+M2 验收。
