from orchestrator.adapters.base import HarnessAdapter, HarnessResult
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.ledger import k3_week_tokens
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import transition
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket
from orchestrator.daemon.events import read_events

from test_routing import _git_repo


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


def test_architect_stays_for_approval(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p2_designing"
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(), tmp_path)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "p2_designing"
    assert t2.owner_role == "boss"


def test_acceptance_timeout_counts_as_failed(pool, tmp_path, monkeypatch):
    # 复检 subprocess 超时不许冒泡:按复检失败处理(搭车修复 T3)
    import subprocess as sp
    from orchestrator.daemon import runner
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "sleep 5",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)

    def boom(cmd, cwd, timeout=600):
        raise sp.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(runner, "_run_acceptance", boom)

    advance_once(pool, t.id, FakeHarness(), proj)  # harness 谎报 done,复检超时
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "pending"
    evts = [e for e in read_events(pool, t.id) if e["event"] == "task_run"]
    assert evts[-1]["verify"] == "failed"
    assert "复检超时" in evts[-1]["output"]


class StubAdapter(HarnessAdapter):
    name = "claude_code"

    def run(self, packet):
        return HarnessResult(status="done",
                             tokens={"input_tokens": 100, "output_tokens": 50})


def test_role_run_records_k3_cost(pool, tmp_path):
    # Finding 1:非 p3 的 role_run 烧掉的 k3 token 必须入台账,否则配额闸水位偏低
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p1_drafting"
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, StubAdapter(), tmp_path, cfg=cfg)
    assert k3_week_tokens(pool) == 150


class CacheReadStubAdapter(HarnessAdapter):
    name = "claude_code"

    def run(self, packet):
        return HarnessResult(status="done", tokens={
            "input_tokens": 100, "output_tokens": 50,
            "cache_read": 10**6,               # 缓存命中不得计入周水位
            "detail": {"note": "嵌套字段"},      # 非 int 字段不得炸 TypeError
        })


def test_ledger_counts_only_input_output_tokens(pool, tmp_path):
    # Finding S1:台账口径只算 input+output;cache_read 虚高与嵌套 dict 都不得入账/报错
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p1_drafting"
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, CacheReadStubAdapter(), tmp_path, cfg=cfg)
    assert k3_week_tokens(pool) == 150


def test_model_for_none_models_section():
    # 复审 round 1:yaml 空 `models:` 段解析为 {"models": None},不得穿透默认值抛 AttributeError
    from orchestrator.daemon.runner import ROLE_MODEL, _model_for
    assert _model_for({"models": None}, "dev") == ROLE_MODEL["dev"]
    assert _model_for(None, "dev") == ROLE_MODEL["dev"]


def test_consult_failure_keeps_consult_chance(pool, tmp_path):
    # Finding 2:会诊自身失败不得烧掉唯一会诊机会(consulted 不置位、attempts 不重置)
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 3}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    dev = FakeHarness(script=["failed"] * 5)
    consult = FakeHarness(script=["failed", "done"])  # 第一次会诊失败,第二次成功
    r1 = advance_once(pool, t.id, dev, proj, cfg=cfg, consult_adapter=consult)
    assert r1.startswith("consult:")
    t1 = load_ticket(pool, t.id)
    assert not t1.tasks[0].get("consulted")   # 会诊机会保留
    assert t1.state == "p3_running"           # 任务还可再会诊,未挂起
    r2 = advance_once(pool, t.id, dev, proj, cfg=cfg, consult_adapter=consult)
    assert r2.startswith("consult:")
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["consulted"] is True   # 会诊成功后才置位
    consults = [e for e in read_events(pool, t.id) if e["event"] == "consult"]
    assert [e["status"] for e in consults] == ["failed", "done"]  # 事件如实记


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


def test_three_failed_tasks_suspend_ticket(pool, tmp_path):
    """3 个任务各自会诊后判负 → 第 3 个判负时整单挂起 consult_exhausted(spec §5.2 工单级)"""
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": f"task-{i}", "title": "a", "acceptance_cmd": "exit 0",
         "depends_on": [], "status": "pending", "attempts": 0}
        for i in (1, 2, 3)
    ]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    h = FakeHarness(script=["failed"] * 30)
    consult = FakeHarness()   # 会诊永远 done(给出诊断),但 dev 就是修不好
    # 每任务:retry×2 → 会诊 → 再败判负(4 轮);判负≠挂单,还有 ready 任务继续派
    for _ in range(3):
        advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)
    r = advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)
    assert r == "task_failed:task-1"
    t1 = load_ticket(pool, t.id)
    assert t1.tasks[0]["status"] == "failed"
    assert t1.consult_count == 1
    assert t1.state == "p3_running"          # 第 1 个判负,工单不挂
    for _ in range(4):                        # task-2 同样判负
        advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[1]["status"] == "failed"
    assert t2.consult_count == 2
    assert t2.state == "p3_running"          # 第 2 个判负,工单仍不挂
    for _ in range(4):                        # task-3 判负 → 第 3 个,整单挂起
        advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)
    t3 = load_ticket(pool, t.id)
    assert t3.tasks[2]["status"] == "failed"
    assert t3.consult_count == 3
    assert t3.state == "suspended"
    codes = [e.get("reason_code") for e in read_events(pool, t.id) if e["event"] == "suspended"]
    assert "consult_exhausted" in codes


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


def test_none_budget_survives_cap_gate(pool, tmp_path):
    # 搭车 T1:手改 YAML 把 budget 抹成 None 时,工单帽闸 .get 不得 AttributeError
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    import yaml
    path = pool / "tickets" / f"{t.id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["budget"] = None
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8", newline="\n")
    msg = advance_once(pool, t.id, FakeHarness(), proj)
    assert msg == "task:task-1:done"


def test_all_done_goes_p4_even_when_daily_cap_exceeded(pool, tmp_path):
    """完工判定优先于成本闸:任务全 done 且 ds 日线超线 → p4,不得 blocked/suspended(T1 评审观察)"""
    from orchestrator.daemon.ledger import append_ledger
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "done", "attempts": 1}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 1}}
    append_ledger(pool, "deepseek", 5.0, "cny", "T-other", "dev", "dsh")
    h = FakeHarness()
    msg = advance_once(pool, t.id, h, proj, cfg=cfg)
    assert msg == "auto: p4_verifying"
    assert load_ticket(pool, t.id).state == "p4_verifying"
    assert not h.received
