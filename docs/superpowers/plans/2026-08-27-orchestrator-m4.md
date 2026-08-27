# 编排器 M4 实施计划:Dashboard v1 + 成本闸收尾

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。Steps 用 checkbox。

**Goal:** 交付 Dashboard v1(总览+审批中心+工单详情,浏览器完成全部审批),并清零 M3 遗留的成本/熔断前置项,为 SK-main 真实接入铺路。

**Architecture:** Flask 3.1(已装)轻量 HTTP 服务,服务端渲染(Jinja2),读 pool/ 文件直出 —— 无独立状态,approval POST 复用 statemachine 同一套迁移函数。成本侧:ds 日线闸在派发入口拦截,dev 失败也记账,预算帽超帽即挂。

**Tech Stack:** Python 3.11、Flask 3.1.3、pytest(Flask test_client)

**Spec:** `docs/superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md`(Dashboard 节、§5.2 工单级熔断、§5.3 台账)

## Global Constraints

- encoding="utf-8"/newline="\n";既有 78 测试全绿保持
- Dashboard 是文件状态的只读视图+审批按钮,不得引入第二个状态权威;审批 POST 必须走 `orchestrator.daemon.statemachine` 的同一函数
- 密钥不得出现在任何模板/日志/页面;页面不显示 key 相关信息
- v1 无认证,绑定 127.0.0.1(局域网开放属 v2 决策);dashboard 端口默认 8321
- 分支 `feature/orchestrator-m4`,每 Task 一个 commit

---

### Task 1: 成本口径收尾(dev 失败记账 + 预算帽 + ds 日线闸)

**Files:**
- Modify: `orchestrator/daemon/runner.py`
- Test: `tests/orchestrator/test_runner.py`、`tests/orchestrator/test_routing.py` 追加

**Interfaces:**
- Produces:
  - dev 任务**失败也记账**(retry/consult 路径每次 harness 调用都 _record_cost —— DS 现金真实消耗,不问成败)
  - 工单预算帽:`ds_ticket_cost(pool, ticket.id) > ticket.budget["token_cap_cny"]`(新预算字段,默认 10.0)→ suspend(reason="工单预算帽",reason_code="budget_cap")
  - ds 日线闸:advance_once 进入 p3 派发前 `ds_daily_exceeded(pool, cfg)` → 返回 `"blocked: ds 日现金线"`,不派发(已在跑的不追杀死,语义=停止派发新任务)
  - ticket.budget 新字段 `token_cap_cny: float = 10.0`(ticket.py 默认值扩展,旧 YAML 无此字段时 validate 不报错)

- [ ] **Step 1: 写失败测试**

```python
def test_dev_failure_records_cost(pool, tmp_path):
    """DS 失败尝试也烧现金,必须入账"""
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}

    class StubDsh(HarnessAdapter):
        name = "dsh"
        def run(self, packet):
            return HarnessResult(status="failed", output="boom", cost_cny=0.5)
    advance_once(pool, t.id, StubDsh(), proj, cfg=cfg, consult_adapter=FakeHarness())
    from orchestrator.daemon.ledger import ds_ticket_cost
    assert ds_ticket_cost(pool, t.id) == 0.5


def test_daily_cap_blocks_dispatch(pool, tmp_path):
    """ds 日线超线 → 不派发新任务"""
    from orchestrator.daemon.ledger import append_ledger
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 1}}
    append_ledger(pool, "deepseek", 5.0, "cny", "T-other", "dev", "dsh")
    h = FakeHarness()
    msg = advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=FakeHarness())
    assert msg.startswith("blocked:")
    assert not h.received   # 一个任务都没派


def test_ticket_budget_cap_suspends(pool, tmp_path):
    """工单现金帽超帽即挂"""
    from orchestrator.daemon.ledger import append_ledger
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.budget = {"token_cap": 500000, "token_cap_cny": 1.0}
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    append_ledger(pool, "deepseek", 2.0, "cny", t.id, "dev", "dsh")
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, FakeHarness(), proj, cfg=cfg, consult_adapter=FakeHarness())
    assert load_ticket(pool, t.id).state == "suspended"
```

注:HarnessAdapter/HarnessResult import 自 orchestrator.adapters.base;`_git_repo` 复用 test_routing 的 fixture 函数(若跨文件不可 import,复制到本文件)。

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**

runner.py 要点:
1. `run_dev_tasks` 在 `result = adapter.run(packet)` 之后、`if cfg: _record_cost(pool, ticket, adapter, result, "dev")`(不分成败,移出 done 分支)
2. 派发前闸(run_dev_tasks 开头,lazy-load 之后):
```python
        if cfg and ds_daily_exceeded(pool, cfg):
            return "blocked: ds 日现金线"
        if ds_ticket_cost(pool, ticket.id) > ticket.budget.get("token_cap_cny", 10.0):
            suspend(pool, ticket, actor="system", reason="工单预算帽")
            return "suspend: 工单预算帽"
```
3. ticket.py:`budget` 默认工厂加 `"token_cap_cny": 10.0`(旧 YAML 读取不受影响,dict 缺键用 .get 兜底)
4. import 更新:from orchestrator.daemon.ledger import append_ledger, ds_daily_exceeded, ds_ticket_cost

- [ ] **Step 4: 全量测试** → 全绿(注意既有 test_k3_quota_blocks_consult 等 cfg 无 ds 键场景:ds_daily_exceeded 需要 cfg["budgets"]["ds_daily_cny"] 键,确认旧测试 cfg 都带;不带则闸内 .get 兜底)
- [ ] **Step 5: Commit** —— `feat(orchestrator): dev 失败记账 + 工单现金帽 + ds 日线派发闸`

---

### Task 2: 3-会诊整单挂起 + --consult-fake + suspend reason_code

**Files:**
- Modify: `orchestrator/daemon/runner.py`、`orchestrator/daemon/cli.py`、`orchestrator/daemon/statemachine.py`
- Test: 追加

**Interfaces:**
- Produces:
  - 工单级会诊计数:ticket 新字段 `consult_count: int = 0`;**每任务会诊≤1(任务级),会诊后仍失败=任务判负(不挂单,继续其他 ready);判负任务数达 3 → 整单 suspend(reason="连续 3 个任务走到会诊级:疑似设计/切片问题", reason_code="consult_exhausted")**(spec §5.2 工单级规则;判负后无 ready 且非全 done → suspend circuit_exhausted)
  - `orc advance --consult-fake`:会诊也用 FakeHarness(CLI 失败演练不再误烧 k3)
  - suspend() 增加可选 `reason_code: str | None = None`,写入事件(枚举:budget_cap/daily_cap/circuit_exhausted/consult_exhausted/quota_exceeded/deadlock/load_failed/release_failed/verify_failed/manual)

- [ ] **Step 1: 写失败测试**

```python
def test_third_consult_suspends_ticket(pool, tmp_path):
    """3 次会诊未解决 → 整单挂起(spec §5.2)"""
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    h = FakeHarness(script=["failed"] * 20)
    consult = FakeHarness()   # 会诊永远 done(给出诊断),但 dev 就是修不好
    # 每轮:3 次 dev 失败 → 1 次会诊 → dev 再失败(attempts 重置后)
    for _ in range(12):
        advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)
        if load_ticket(pool, t.id).state == "suspended":
            break
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    assert t2.consult_count >= 3
    from orchestrator.daemon.events import read_events
    codes = [e.get("reason_code") for e in read_events(pool, t.id) if e["event"] == "suspended"]
    assert "consult_exhausted" in codes
```

(注:会诊后 attempts=MAX_RETRY-1,再失败一次即 attempts=3 → 又触发会诊;循环 12 次足够到 3 次会诊)

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**

- statemachine.suspend 签名加 `reason_code=None`,事件带上;各调用点传入对应枚举值
- runner 会诊分支:`ticket.consult_count += 1`(save);会诊后 dev 再失败且 consult_count >= 3 → 整单 suspend(reason_code="consult_exhausted"),不再 retry/consult
- ticket.py:dataclass 加 `consult_count: int = 0`
- cli.py:advance 加 `--consult-fake`(consult_adapter=FakeHarness())
- [ ] **Step 4: 全量测试** → 全绿
- [ ] **Step 5: Commit** —— `feat(orchestrator): 3-会诊整单挂起 + consult-fake 开关 + suspend reason_code`

---

### Task 3: 复检证据保尾 + 事故单结构化回链(小项批量)

**Files:**
- Modify: `orchestrator/daemon/runner.py`
- Test: 追加

**Interfaces:**
- Produces:
  - 复检失败时 output 组装改为"复检证据在前":`result.output = f"[acceptance 复检失败 exit={code}] {tail1000}\n--- harness 输出(截断) ---\n{orig[:500]}"`(事件 [:500] 与 retry_prompt [:800] 切头时保留复检证据)
  - P5 事故工单结构化回链:incident 工单 YAML 带 `related_ticket: <原单 id>`;原单事件流追加 `incident_created` 事件(含新工单 id);ticket.py dataclass 加 `related_ticket: str | None = None`

- [ ] **Step 1: 写失败测试**

```python
def test_recheck_evidence_kept_at_head(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 1",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)

    class LoudHarness(FakeHarness):
        def run(self, packet):
            from orchestrator.adapters.base import HarnessResult
            return HarnessResult(status="done", output="x" * 5000)   # 长输出
    advance_once(pool, t.id, LoudHarness(), proj)
    from orchestrator.daemon.events import read_events
    ev = [e for e in read_events(pool, t.id) if e["event"] == "task_run"][-1]
    assert "acceptance 复检失败" in ev["output"]   # 截断后证据仍在头部


def test_incident_links_back(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p5_releasing"
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(script=["failed"]), tmp_path)
    from orchestrator.daemon.ticket import load_ticket as lt
    from pathlib import Path as P
    inc_id = [f.stem for f in (pool / "tickets").glob("*.yaml") if f.stem != t.id][0]
    assert lt(pool, inc_id).related_ticket == t.id
    from orchestrator.daemon.events import read_events
    assert any(e["event"] == "incident_created" and e.get("incident") == inc_id
               for e in read_events(pool, t.id))
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**(runner 复检段 output 组装顺序;P5 分支建单时 related_ticket=t.id + 原单 append_event("incident_created"))
- [ ] **Step 4: 全量测试** → 全绿
- [ ] **Step 5: Commit** —— `feat(orchestrator): 复检证据保尾 + 事故单结构化回链`

---

### Task 4: Dashboard 骨架 + 总览页

**Files:**
- Create: `orchestrator/dashboard/__init__.py`、`orchestrator/dashboard/app.py`、`orchestrator/dashboard/views.py`(数据装配)、`orchestrator/dashboard/templates/base.html`、`index.html`
- Test: `tests/orchestrator/test_dashboard.py`

**Interfaces:**
- Produces:
  - `create_app(pool_dir: Path, cfg: dict) -> Flask`(测试可注入 tmp pool)
  - `GET /` 总览:k3 周水位(gateway.k3_effective_week_tokens vs budget,百分比条)/ DS 今日与本月现金(ledger)/ 待审批数(处于 APPROVALS 键状态的工单数)/ 运行中(p3_running/p4_verifying/p5_releasing/monitoring 工单)/ suspended 数 / 今日事件摘要(当日事件按工单分组计数)
  - 数据装配函数 `overview_data(pool, cfg) -> dict`(纯函数,可单测)

- [ ] **Step 1: 写失败测试(Flask test_client)**

```python
import pytest
from orchestrator.dashboard.app import create_app
from orchestrator.daemon.ticket import new_ticket
from orchestrator.daemon.statemachine import transition


@pytest.fixture
def client(pool):
    cfg = {"budgets": {"k3_week_token_budget": 2000000, "ds_daily_cny": 30},
           "gateway": {"url": "http://127.0.0.1:1"}}   # 不可达 → 回退本地台账
    t = new_ticket(pool, project="p", summary="测试工单")
    transition(pool, t, "p0_proposed", actor="pm")
    app = create_app(pool, cfg)
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "总览" in html
    assert "测试工单" not in html      # 总览不列工单明细(那是审批中心)
    assert "待审批" in html
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**

app.py 骨架:

```python
from flask import Flask, render_template
from pathlib import Path
from orchestrator.dashboard import views


def create_app(pool_dir: Path, cfg: dict) -> Flask:
    app = Flask(__name__)
    app.config["POOL"] = Path(pool_dir)
    app.config["CFG"] = cfg

    @app.get("/")
    def index():
        return render_template("index.html", **views.overview_data(
            app.config["POOL"], app.config["CFG"]))

    return app
```

views.overview_data:读 pool/tickets/*.yaml(load_ticket)、ledger、k3_effective_week_tokens;返回 {k3_used, k3_budget, k3_pct, ds_today, ds_month, pending_approval, running, suspended, today_events}。模板:base.html(导航:总览/审批中心)+ index.html(指标卡片 + 简单 CSS,内联 <style>,深色可选不做)。

- [ ] **Step 4: 跑测试确认通过** → 全绿
- [ ] **Step 5: Commit** —— `feat(dashboard): Flask 骨架 + 总览页`

---

### Task 5: 审批中心

**Files:**
- Modify: `orchestrator/dashboard/app.py`、`orchestrator/dashboard/views.py`
- Create: `orchestrator/dashboard/templates/approvals.html`
- Test: 追加

**Interfaces:**
- Produces:
  - `GET /approvals`:分组列出 —— P0 提案(p0_proposed)/ P2 设计(p2_designing 且 owner=boss)/ P5 发布(p5_ready)/ 探针草稿(draft 且 created_by=probe)/ 挂起(suspended);每条显示 id/项目/摘要/类型
  - `POST /approve/<id>`(= statemachine.transition APPROVALS 映射,actor="boss")、`POST /reject/<id>`(→closed)、`POST /resume/<id>`;成功 redirect 回 /approvals,失败(非法迁移)显示错误
  - draft(probe) 的"采纳"按钮 = transition(draft→p0_proposed, actor="pm")?——老板代 PM 提交:用 actor="pm" 不合理。**裁决**:审批中心对 draft 的采纳走 `transition(t, "p0_proposed", actor="boss")` —— 需放宽 TRANSITIONS["draft"]["p0_proposed"] 允许 {"pm", "boss"}(探针草稿本来就要老板把关,老板直接提交省一跳;事件日志 actor=boss 真实记录是谁点的)

- [ ] **Step 1: 写失败测试**

```python
def test_approvals_groups(client):
    r = client.get("/approvals")
    assert r.status_code == 200
    assert "P0 提案" in r.get_data(as_text=True)


def test_approve_p0_via_post(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p1_drafting"
    from orchestrator.daemon.events import read_events
    assert read_events(pool, t.id)[-1]["actor"] == "boss"


def test_probe_draft_adoptable(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    t = new_ticket(pool, project="p", summary="测试缺口:payments", created_by="probe")
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p0_proposed"
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**(views.pending_groups(pool) 分组;app.py 三个 POST 端点复用 statemachine;TRANSITIONS["draft"]["p0_proposed"] 改 {"pm", "boss"};approvals.html 分组卡片+表单按钮)
- [ ] **Step 4: 全量测试** → 全绿
- [ ] **Step 5: Commit** —— `feat(dashboard): 审批中心(分组+一键批驳/采纳/恢复)`

---

### Task 6: 工单详情页

**Files:**
- Modify: `orchestrator/dashboard/app.py`、`orchestrator/dashboard/views.py`
- Create: `orchestrator/dashboard/templates/ticket.html`
- Test: 追加

**Interfaces:**
- Produces:
  - `GET /ticket/<id>`:工单全字段 + 任务列表(status/attempts/worktree)+ 事件流(倒序)+ 成本(ds_ticket_cost)+ 产物指针列表
  - `views.ticket_detail(pool, ticket_id) -> dict | None`

- [ ] **Step 1: 写失败测试**

```python
def test_ticket_detail(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="quant-lab", summary="详情页测试")
    transition(pool, t, "p0_proposed", actor="pm")
    r = client.get(f"/ticket/{t.id}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "详情页测试" in html and "quant-lab" in html
    assert "state_changed" in html   # 事件流
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现 + 全量测试**
- [ ] **Step 4: Commit** —— `feat(dashboard): 工单详情页(任务/事件流/成本)`

---

### Task 7: orc dashboard CLI + SK-main 接入登记 + 收尾

**Files:**
- Modify: `orchestrator/daemon/cli.py`(`orc dashboard [--port 8321] [--host 127.0.0.1]`)、`orchestrator.yaml`(projects 登记 orc-e2e;SK-main 待用户决定路径后登记)
- Modify: `docs/architecture.md`(平台层补 dashboard 一节)
- Test: CLI smoke(dashboard 命令可导入创建 app,不真起服务)

- [ ] **Step 1: 实现 + 测试**

```python
# cli.py
c = sub.add_parser("dashboard"); c.add_argument("--port", type=int, default=8321); c.add_argument("--host", default="127.0.0.1")
...
elif args.cmd == "dashboard":
    from orchestrator.dashboard.app import create_app
    create_app(_pool(), _cfg()).run(host=args.host, port=args.port, debug=False)
```

orchestrator.yaml projects 登记:

```yaml
projects:
  orc-e2e: d:/workspace/tmp/orc-e2e
```

- [ ] **Step 2: 全量测试 + slow 手验**(`orc dashboard` 起服务,浏览器开 http://127.0.0.1:8321 过一遍:总览→审批→详情)
- [ ] **Step 3: Commit + push** —— M4 完成

---

## Self-Review 记录

- **Spec 覆盖**:Dashboard 节 v1(总览+审批中心)+ 工单详情(v1.1 的需求池列表精简为详情页,泳道看板留 v1.1);§5.2 工单级 3-会诊挂起(T2);§5.3 预算帽/日线(T1);M3 终审 M4 清单:截断保尾(T3)、reason_code(T2)、事故单回链(T3)、--consult-fake(T2)、dev 失败记账(T1)
- **类型一致**:create_app/overview_data/pending_groups/ticket_detail/reason_code 枚举跨任务一致
- **有意留白**:泳道看板/时间线/成本页/角色页(v1.1+);局域网多参与人+认证(v2);探针收件箱(M5 随探针);SK-main 正式接入(走查时登记 projects)
