# 编排器 M3 实施计划:熔断阶梯 + 双资源台账

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。Steps 用 checkbox。

**Goal:** 给编排器装上质量与成本的刹车:任务级熔断阶梯(重试→会诊→挂起)、双资源成本台账(k3 周配额/DeepSeek 现金)、验收命令独立复检、事故工单通道。

**Architecture:** 全部落在既有 M1/M2 骨架上:ledger.py(台账,纯追加)与 circuitbreaker.py(阶梯判定,纯函数)为独立模块;runner 集成二者;事件日志仍是唯一叙事。k3 配额用静态预算代理(orchestrator.yaml),真实配额接口留待后续。

**Tech Stack:** Python 3.11、pyyaml、pytest(沿用 M1/M2 环境)

**Spec:** `docs/superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md` 第 5 节(熔断/台账)+ 第 2 节(事故工单)+ 第 4 节(可复现性复检哲学在执行侧的落地)

## Global Constraints

- 文件读写 `encoding="utf-8"`,写文件 `newline="\n"`;subprocess 一律 `encoding="utf-8", errors="replace"`
- 测试全用 tmp_path pool;不动 quant-lab / tiktok-ecommerce-ai
- 每 Task 结束 commit;全程在分支 `feature/orchestrator-m3`
- 熔断语义(spec §5.2):dsh 重试最多 3 次 → 架构师会诊最多 1 次 → 挂起;k3 会诊受配额闸:配额超线时仅 incident 工单可会诊
- 既有 41 个测试必须保持全绿(允许按本计划显式修改的断言除外)

---

### Task 1: 台账 ledger.py + 配置扩展

**Files:**
- Create: `orchestrator/daemon/ledger.py`
- Modify: `orchestrator.yaml`(加 budgets 段)
- Test: `tests/orchestrator/test_ledger.py`

**Interfaces:**
- Produces:
  - `append_ledger(pool, resource, amount, unit, ticket_id, role, model) -> dict` — 追加一条到 `pool/ledger.jsonl` 并返回条目(带 `ts` UTC ISO)
  - `k3_week_tokens(pool, now=None) -> int` — 当前 ISO 周内 resource=="k3" 的 amount 合计(unit=="tokens")
  - `ds_day_cost(pool, day=None) -> float` — 当日 resource=="deepseek" 合计(unit=="cny")
  - `ds_ticket_cost(pool, ticket_id) -> float`
  - `k3_budget_exceeded(pool, cfg) -> bool` — k3_week_tokens > cfg["budgets"]["k3_week_token_budget"]
  - `ds_daily_exceeded(pool, cfg) -> bool`

`orchestrator.yaml` 新增:

```yaml
budgets:
  k3_week_token_budget: 200000   # 编排器周 token 额度(静态代理,真实配额接口后续)
  ds_daily_cny: 30
```

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime, timezone
from orchestrator.daemon.ledger import (
    append_ledger, ds_day_cost, ds_daily_exceeded, ds_ticket_cost,
    k3_budget_exceeded, k3_week_tokens,
)

CFG = {"budgets": {"k3_week_token_budget": 1000, "ds_daily_cny": 5}}


def test_append_and_week_sum(pool):
    append_ledger(pool, "k3", 300, "tokens", "T-1", "pm", "k3")
    append_ledger(pool, "k3", 200, "tokens", "T-1", "architect", "k3")
    append_ledger(pool, "deepseek", 1.5, "cny", "T-1", "dev", "deepseek-v4-pro")
    assert k3_week_tokens(pool) == 500
    assert ds_day_cost(pool) == 1.5
    assert ds_ticket_cost(pool, "T-1") == 1.5


def test_budget_flags(pool):
    assert not k3_budget_exceeded(pool, CFG)
    append_ledger(pool, "k3", 1001, "tokens", "T-1", "pm", "k3")
    assert k3_budget_exceeded(pool, CFG)
    assert not ds_daily_exceeded(pool, CFG)
    append_ledger(pool, "deepseek", 6.0, "cny", "T-2", "dev", "deepseek-v4-pro")
    assert ds_daily_exceeded(pool, CFG)


def test_empty_ledger(pool):
    assert k3_week_tokens(pool) == 0
    assert ds_day_cost(pool) == 0.0
```

- [ ] **Step 2: 跑测试确认失败** → FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现**

```python
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
```

- [ ] **Step 4: 跑测试确认通过** → 3 passed;并更新 orchestrator.yaml
- [ ] **Step 5: Commit** —— `feat(orchestrator): 双资源台账 ledger`

---

### Task 2: 切片健壮性(循环依赖 + 死锁挂起)

**Files:**
- Modify: `orchestrator/daemon/slicer.py`(load_task_list 加循环依赖检测)
- Modify: `orchestrator/daemon/runner.py`(无 ready 且非全 done → suspend,不再是 idle)
- Test: `tests/orchestrator/test_slicer.py`、`tests/orchestrator/test_routing.py` 追加

**Interfaces:**
- Produces: `load_task_list` 对循环依赖抛 `ValueError("循环依赖: ...")`;`run_dev_tasks` 死锁时 suspend(reason 含"依赖")

- [ ] **Step 1: 写失败测试**

test_slicer.py 追加:

```python
def test_circular_dependency_rejected(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text(
        "- id: a\n  title: x\n  acceptance_cmd: c\n  depends_on: [b]\n"
        "- id: b\n  title: y\n  acceptance_cmd: c\n  depends_on: [a]\n",
        encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="循环依赖"):
        load_task_list(f)
```

test_routing.py 追加:

```python
def test_deadlocked_tasks_suspend(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": "a", "title": "x", "acceptance_cmd": "true", "depends_on": ["gone"],
         "status": "pending", "attempts": 0},
    ]
    save_ticket(pool, t)
    msg = advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    from orchestrator.daemon.events import read_events
    assert any("依赖" in str(e.get("reason", "")) for e in read_events(pool, t.id))
```

(注:tasks 里 depends_on 指向不存在 id 的手工注入场景 —— 直接注入绕过 load_task_list 校验,runner 兜底)

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

slicer.py 的 load_task_list 尾部追加:

```python
    # 循环依赖检测(DFS 三色标记)
    by_id = {t["id"]: t for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in by_id}

    def visit(i, stack):
        color[i] = GRAY
        for dep in by_id[i].get("depends_on", []):
            if dep not in by_id:
                continue
            if color[dep] == GRAY:
                raise ValueError(f"循环依赖: {' -> '.join(stack + [i, dep])}")
            if color[dep] == WHITE:
                visit(dep, stack + [i])
        color[i] = BLACK

    for i in by_id:
        if color[i] == WHITE:
            visit(i, [])
    return tasks
```

runner.py 的 run_dev_tasks,`if not ready:` 分支改为:

```python
    if not ready:
        if all(t["status"] == "done" for t in ticket.tasks):
            transition(pool, ticket, "p4_verifying", actor="system")
            return "auto: p4_verifying"
        suspend(pool, ticket, actor="system",
                reason="无可派发任务且未完成:依赖死锁或依赖缺失")
        return "suspend: 依赖死锁"
```

注意:`test_e2e_fake.py` 的 p3 空 tasks 场景(all([])==True)行为不变,不受影响。

- [ ] **Step 4: 跑测试确认通过** → 新测试 passed,41 旧测试全绿
- [ ] **Step 5: Commit** —— `feat(orchestrator): 切片循环依赖检测与死锁挂起`

---

### Task 3: 验收命令独立复检

**Files:**
- Modify: `orchestrator/daemon/runner.py`(run_dev_tasks:harness 说 done 后独立跑 acceptance_cmd)
- Test: `tests/orchestrator/test_routing.py` 追加

**Interfaces:**
- Produces: run_dev_tasks 复检逻辑 —— done 且 task 有 acceptance_cmd → 在 worktree 里 `subprocess.run(cmd, shell=True, executable="bash")`,退出码非 0 视为失败(result.status 改 failed,output 追加复检输出,事件加 `verify: "failed"`)

- [ ] **Step 1: 写失败测试**

```python
def test_acceptance_recheck_catches_lying_harness(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 1",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    h = FakeHarness()  # harness 谎报 done
    advance_once(pool, t.id, h, proj)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "pending"   # 复检揪出,不算 done
    from orchestrator.daemon.events import read_events
    evts = [e for e in read_events(pool, t.id) if e["event"] == "task_run"]
    assert evts[-1]["verify"] == "failed"


def test_acceptance_recheck_pass(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(), proj)
    assert load_ticket(pool, t.id).tasks[0]["status"] == "done"
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

runner.py 顶部加 `import subprocess`;run_dev_tasks 中 result 返回后、判 done 前插入:

```python
    verify = None
    if result.status == "done" and task.get("acceptance_cmd"):
        r = subprocess.run(task["acceptance_cmd"], shell=True, executable="bash",
                           cwd=wt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        verify = "passed" if r.returncode == 0 else "failed"
        if r.returncode != 0:
            result.status = "failed"
            result.output += f"\n[acceptance 复检失败 exit={r.returncode}]\n{(r.stdout + r.stderr)[-1000:]}"
```

task_run 事件 append 加 `verify=verify`。

注意:既有测试 `test_p3_dispatches_ready_tasks` 用 acceptance_cmd `"true"` —— bash 的 true 退出 0,仍绿。

- [ ] **Step 4: 跑测试确认通过** → 全绿
- [ ] **Step 5: Commit** —— `feat(orchestrator): 验收命令独立复检(防 harness 谎报)`

---

### Task 4: 熔断阶梯 circuitbreaker.py

**Files:**
- Create: `orchestrator/daemon/circuitbreaker.py`
- Test: `tests/orchestrator/test_circuitbreaker.py`

**Interfaces:**
- Consumes: TaskPacket
- Produces:
  - `MAX_RETRY = 3`
  - `next_action(task: dict) -> str` — "retry" | "consult" | "suspend":attempts < 3 → retry;未 consulted → consult;否则 suspend
  - `retry_prompt(task: dict, base_prompt: str, last_output: str) -> str` — 重试 prompt:base + `\n\n第 {attempts+1} 次尝试。上次错误:\n{last_output[:800]}\n先分析失败原因再动手。`
  - `consult_packet(task: dict, ticket, last_output: str, workdir: Path) -> TaskPacket` — role="architect",prompt = 失败任务包(任务描述+错误输出+工单摘要+"给出诊断与修复建议,不写代码")

- [ ] **Step 1: 写失败测试**

```python
from orchestrator.daemon.circuitbreaker import MAX_RETRY, consult_packet, next_action, retry_prompt
from orchestrator.daemon.ticket import new_ticket


def _t(attempts, consulted=False):
    return {"id": "task-1", "attempts": attempts, "consulted": consulted, "title": "建模型"}


def test_ladder():
    assert next_action(_t(0)) == "retry"
    assert next_action(_t(MAX_RETRY - 1)) == "retry"
    assert next_action(_t(MAX_RETRY)) == "consult"
    assert next_action(_t(MAX_RETRY, consulted=True)) == "suspend"


def test_retry_prompt_carries_context():
    p = retry_prompt(_t(1), "原始任务", "assert 1==2 failed")
    assert "原始任务" in p and "第 2 次尝试" in p and "assert 1==2" in p


def test_consult_packet(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="加缓存")
    pkt = consult_packet(_t(3), t, "exit 1: boom", tmp_path)
    assert pkt.role == "architect"
    assert "exit 1: boom" in pkt.prompt and "诊断" in pkt.prompt and "加缓存" in pkt.prompt
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

```python
"""任务级熔断阶梯:重试(≤3)→ 架构师会诊(≤1)→ 挂起。spec §5.2。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.adapters.base import TaskPacket

MAX_RETRY = 3


def next_action(task: dict) -> str:
    if task["attempts"] < MAX_RETRY:
        return "retry"
    if not task.get("consulted"):
        return "consult"
    return "suspend"


def retry_prompt(task: dict, base_prompt: str, last_output: str) -> str:
    return (
        f"{base_prompt}\n\n第 {task['attempts'] + 1} 次尝试。上次错误:\n"
        f"{last_output[:800]}\n先分析失败原因再动手。"
    )


def consult_packet(task: dict, ticket, last_output: str, workdir: Path) -> TaskPacket:
    prompt = (
        f"你是架构师,受邀会诊一个失败任务。\n"
        f"工单: {ticket.id} — {ticket.summary}\n"
        f"任务: {task['id']}: {task['title']}(已失败 {task['attempts']} 次)\n"
        f"错误输出:\n{last_output[:1500]}\n\n"
        f"给出诊断与修复建议(不写代码)。输出格式:根因 / 修复方案 / 是否需要改设计。"
    )
    return TaskPacket(role="architect", prompt=prompt, workdir=workdir,
                    budget=ticket.budget)
```

- [ ] **Step 4: 跑测试确认通过** → 3 passed
- [ ] **Step 5: Commit** —— `feat(orchestrator): 熔断阶梯判定与重试/会诊包`

---

### Task 5: runner 集成熔断 + 配额闸

**Files:**
- Modify: `orchestrator/daemon/runner.py`
- Modify: `orchestrator/daemon/cli.py`(advance 传 cfg 与 consult_adapter)
- Test: `tests/orchestrator/test_runner.py`、`tests/orchestrator/test_routing.py` 追加

**Interfaces:**
- Consumes: circuitbreaker/ledger/各适配器
- Produces:
  - `advance_once(pool, ticket_id, adapter, project_dir, cfg=None, consult_adapter=None)` — 签名扩展,向后兼容(cfg/consult_adapter 默认 None:None 时不记账不会诊,保持旧测试行为)
  - run_dev_tasks 失败路径改造:
    1. attempts+=1 后 `next_action(task)`:
       - retry → task 留 pending,**不 suspend**,返回 `retry:<id>:<attempts>`(下次 advance 用 retry_prompt 重试)
       - consult → 若 cfg 且 k3_budget_exceeded 且 ticket.type != "incident" → suspend(reason="k3 配额超线,会诊关闭");否则用 consult_adapter(无则 get_adapter("claude_code"))跑 consult_packet,task["consulted"]=True、task["consult_note"]=诊断 output,事件 `consult`;会诊后 attempts 重置为 MAX_RETRY-1(会诊后只再给 1 次机会)
       - suspend → 原逻辑
    2. 成功路径记账:cfg 存在时 append_ledger(resource 按 adapter.name 映射:claude_code→"k3"/tokens=Σusage 值,ds→"deepseek"/cny=result.cost_cny)
  - 重试时 make_packet 的 prompt 用 retry_prompt 包装
  - cli.py:_pool() 旁加 `_cfg()` 读整个 orchestrator.yaml;advance 传 cfg,consult_adapter=None(生产默认走 get_adapter)

- [ ] **Step 1: 写失败测试**

```python
def test_retry_then_success(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    h = FakeHarness(script=["failed", "done"])
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    r1 = advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=FakeHarness())
    assert r1.startswith("retry:")
    assert load_ticket(pool, t.id).state == "p3_running"   # 不挂起
    advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=FakeHarness())
    assert load_ticket(pool, t.id).tasks[0]["status"] == "done"
    assert "第 2 次尝试" in h.received[1].prompt            # 重试 prompt 生效


def test_consult_then_retry_once_then_suspend(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    h = FakeHarness(script=["failed"] * 10)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    consult = FakeHarness()
    for _ in range(2):  # 2 次 retry(第 3 次失败触发会诊)
        advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)
    r = advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)  # 第 3 次失败→consult
    assert r.startswith("consult:")
    assert consult.received and consult.received[0].role == "architect"
    advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)      # 会诊后再失败(attempts 回到 3)
    assert load_ticket(pool, t.id).state == "suspended"


def test_k3_quota_blocks_consult(pool, tmp_path):
    from orchestrator.daemon.ledger import append_ledger
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 3}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10, "ds_daily_cny": 10**9}}
    append_ledger(pool, "k3", 999, "tokens", "T-x", "pm", "k3")
    advance_once(pool, t.id, FakeHarness(script=["failed"]), proj,
                 cfg=cfg, consult_adapter=FakeHarness())
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    from orchestrator.daemon.events import read_events
    assert any("配额" in str(e.get("reason", "")) for e in read_events(pool, t.id))
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现(runner.py 的 run_dev_tasks 失败段与记账)**

关键实现(替换/插入):

```python
from orchestrator.adapters import get_adapter
from orchestrator.daemon.circuitbreaker import (
    MAX_RETRY, consult_packet, next_action, retry_prompt,
)
from orchestrator.daemon.ledger import append_ledger

ADAPTER_RESOURCE = {"claude_code": ("k3", "tokens"), "dsh": ("deepseek", "cny")}


def _record_cost(pool, ticket, adapter, result, role):
    res = ADAPTER_RESOURCE.get(adapter.name)
    if not res:
        return
    resource, unit = res
    amount = sum(result.tokens.values()) if unit == "tokens" else result.cost_cny
    if amount:
        append_ledger(pool, resource, amount, unit, ticket.id, role, adapter.name)
```

失败段(替换原 suspend-only 逻辑):

```python
    task["attempts"] += 1
    append_event(..., verify=verify)  # 原事件保留
    if result.status == "done":
        task["status"] = "done"
        save_ticket(pool, ticket)
        if cfg: _record_cost(pool, ticket, adapter, result, "dev")
        return f"task:{task['id']}:done"

    save_ticket(pool, ticket)  # attempts 已记
    action = next_action(task)
    if action == "retry":
        return f"retry:{task['id']}:{task['attempts']}"
    if action == "consult":
        if cfg and ticket.type != "incident" and k3_budget_exceeded(pool, cfg):
            suspend(pool, ticket, actor="system",
                    reason="k3 配额超线,会诊通道关闭,任务挂起")
            return "suspend: k3 配额超线"
        ca = consult_adapter or get_adapter("claude_code")
        cp = consult_packet(task, ticket, result.output, wt)
        cr = ca.run(cp)
        task["consulted"] = True
        task["consult_note"] = cr.output[:1000]
        task["attempts"] = MAX_RETRY - 1   # 会诊后只再给 1 次
        append_event(pool, ticket.id, "architect", "consult",
                     task=task["id"], status=cr.status, output=cr.output[:500])
        save_ticket(pool, ticket)
        if cfg: _record_cost(pool, ticket, ca, cr, "architect")
        return f"consult:{task['id']}:{cr.status}"
    suspend(pool, ticket, actor="system",
            reason=f"任务 {task['id']} 会诊后仍失败")
    return f"suspend:{task['id']}"
```

重试 prompt:make_packet 调用处,`task["attempts"] > 0` 时 `packet.prompt = retry_prompt(task, packet.prompt, task.get("last_error", ""))`;失败时记 `task["last_error"] = result.output[:800]`。

- [ ] **Step 4: 跑测试确认通过** → 新 3 测试 passed;旧 43 全绿(注意旧失败语义测试 test_failure_suspends 针对非 p3 状态,不受影响;`test_p3_dispatches_ready_tasks` 单次成功不受影响)
- [ ] **Step 5: Commit** —— `feat(orchestrator): runner 集成熔断阶梯与成本记账`

---

### Task 6: 事故工单 + P5 失败通道

**Files:**
- Modify: `orchestrator/daemon/ticket.py`(new_ticket 加 `type` 参数;incident → state="p1_drafting", priority="high")
- Modify: `orchestrator/daemon/runner.py`(p5_releasing 失败 → suspend + 自动建 incident 工单)
- Modify: `orchestrator/daemon/cli.py`(orc new 加 `--type`)
- Test: `tests/orchestrator/test_ticket.py`、`tests/orchestrator/test_runner.py` 追加

**Interfaces:**
- Produces: `new_ticket(pool, project, summary, created_by="human", type="feature")`;incident 工单 state 从 p1_drafting 起步(spec §2 快速通道)

- [ ] **Step 1: 写失败测试**

```python
def test_incident_ticket_fast_lane(pool):
    t = new_ticket(pool, project="p", summary="发布失败", created_by="system", type="incident")
    assert t.state == "p1_drafting"
    assert t.priority == "high"
    assert t.type == "incident"


def test_p5_failure_creates_incident(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p5_releasing"
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(script=["failed"]), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    # 自动事故工单进池
    from pathlib import Path as P
    tickets = list((pool / "tickets").glob("*.yaml"))
    assert len(tickets) == 2
    inc = [f.stem for f in tickets if f.stem != t.id][0]
    from orchestrator.daemon.ticket import load_ticket as lt
    it = lt(pool, inc)
    assert it.type == "incident" and it.state == "p1_drafting"
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

ticket.py:new_ticket 签名加 `type: str = "feature"`;incident 时 `state="p1_drafting", priority="high"`。

runner.py:advance_once 中非 p3 的 WORK_STATES 失败分支(p5_releasing 且 result.status != "done"):

```python
        if t.state == "p5_releasing":
            suspend(pool, t, actor="system", reason=f"发布失败: {result.status}")
            from orchestrator.daemon.ticket import new_ticket as _nt
            _nt(pool, t.project, f"发布失败: {t.id} {t.summary}",
                created_by="system", type="incident")
        else:
            suspend(...)
```

cli.py:orc new 加 `--type`(choices feature/incident,默认 feature)。

- [ ] **Step 4: 跑测试确认通过** → 全绿
- [ ] **Step 5: Commit** —— `feat(orchestrator): 事故工单快速通道与 P5 失败自闭环`

---

### Task 7: 工单 id 原子性(文件锁)

**Files:**
- Modify: `orchestrator/daemon/ticket.py`(_next_id + save 加 O_EXCL 自旋锁)
- Test: `tests/orchestrator/test_ticket.py` 追加(并发 8 线程建单,id 全唯一)

- [ ] **Step 1: 写失败/回归测试**

```python
def test_concurrent_new_ticket_unique_ids(pool):
    import threading
    ids = []
    def mk(i):
        ids.append(new_ticket(pool, project="p", summary=f"s{i}").id)
    threads = [threading.Thread(target=mk, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(ids)) == 8
```

- [ ] **Step 2: 实现** —— new_ticket 全程持锁:

```python
import os, time

def _locked(pool: Path):
    lock = pool / ".lock"
    for _ in range(50):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return lock
        except FileExistsError:
            time.sleep(0.1)
    raise TimeoutError("pool 锁超时")
```

new_ticket 在 `_locked` 后 try/finally `lock.unlink()` 内完成 id 分配+save+事件。

- [ ] **Step 3: 跑测试确认通过** → 全绿
- [ ] **Step 4: Commit** —— `fix(orchestrator): 工单 id 分配加文件锁`

---

### Task 8: M3 e2e + 收尾

**Files:**
- Test: `tests/orchestrator/test_e2e_circuitbreaker.py`

- [ ] **Step 1: 写 e2e:一张工单 P3 遭遇失败→重试→会诊→成功→走到 done,台账/事件完整**

```python
"""M3 验收:熔断阶梯全链路 + 台账记账。"""
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.ledger import ds_day_cost
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import APPROVALS, transition
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket


def test_circuit_breaker_full_lifecycle(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="加缓存")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, load_ticket(pool, t.id), "p1_drafting", actor="boss")
    advance_once(pool, t.id, FakeHarness(), tmp_path)
    transition(pool, load_ticket(pool, t.id), "p2_designing", actor="boss")
    advance_once(pool, t.id, FakeHarness(), tmp_path)
    transition(pool, load_ticket(pool, t.id), "p2_approved", actor="boss")

    t2 = load_ticket(pool, t.id)
    t2.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                 "depends_on": [], "status": "pending", "attempts": 0}]
    t2.state = "p3_running"
    save_ticket(pool, t2)

    dev = FakeHarness(script=["failed", "failed", "failed", "done"])
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    for _ in range(4):  # retry、retry、consult(第 3 次失败)、会诊后成功
        advance_once(pool, t.id, dev, tmp_path, cfg=cfg, consult_adapter=FakeHarness())
    t3 = load_ticket(pool, t.id)
    assert t3.tasks[0]["status"] == "done"

    advance_once(pool, t.id, FakeHarness(), tmp_path)   # p3→p4(auto,空 ready→全 done)
    advance_once(pool, t.id, FakeHarness(), tmp_path)   # qa→p5_ready
    transition(pool, load_ticket(pool, t.id), "p5_releasing", actor="boss")
    advance_once(pool, t.id, FakeHarness(), tmp_path)   # release→monitoring
    advance_once(pool, t.id, FakeHarness(), tmp_path)   # sre→done

    assert load_ticket(pool, t.id).state == "done"
    kinds = [e["event"] for e in read_events(pool, t.id)]
    assert "consult" in kinds and "task_run" in kinds
```

- [ ] **Step 2: 全量测试** → 全绿(含 M1/M2 全部)
- [ ] **Step 3: Commit + push** —— M3 完成

---

## Self-Review 记录

- **Spec 覆盖**:§5.2 任务级阶梯(T4/T5)、工单级预算帽(T1/T5 的配额闸;工单 token_cap 由 acceptance/记账事件承载,dashboard 展示在 M4)、P5 失败事故工单(T6)、§4 闸 2 哲学在执行侧的复检(T3)。观察窗 SRE 巡检调度与台账归档属 M5。
- **类型一致性**:next_action/retry_prompt/consult_packet/append_ledger/k3_budget_exceeded 签名跨 T4-T5 一致;advance_once 扩展向后兼容(cfg/consult_adapter 默认 None,旧测试不变)。
- **有意留白**:k3 真实配额接口(静态预算代理)、DS 现金 token→¥ 换算(dsh usage 解析)待 dsh 安装后补;工单级 token_cap 强制(超额即挂)在 M4 随 dashboard 预算页一起做。
