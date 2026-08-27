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
