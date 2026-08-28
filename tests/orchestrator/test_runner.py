import json
import subprocess

import pytest

from orchestrator.adapters.base import HarnessAdapter, HarnessResult
from orchestrator.adapters.dsh import USAGE_MISSING_MSG
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.ledger import ds_day_calls, ds_ticket_cost, k3_week_tokens
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


def test_none_budget_survives_cap_gate(pool, tmp_path, monkeypatch):
    # 搭车 T1:手改 YAML 把 budget 抹成 None 时,工单帽闸 .get 不得 AttributeError
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    # 验收复检不依赖环境里的 bash(沙箱内 git-bash 可能起不来):stub 掉 _run_acceptance,
    # 本测试只关心 budget=None 时工单帽闸不得 AttributeError、任务照常完工
    from orchestrator.daemon import runner as _runner
    monkeypatch.setattr(_runner, "_run_acceptance",
                        lambda cmd, cwd, timeout=600: subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="", stderr=""))
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


# ---- dsh usage trailer 契约消费 + 台账三字段对齐(T-2026-0828-003 D3) ----

class StubDshAdapter(HarnessAdapter):
    """模拟消费 usage trailer 后的 DshAdapter 产出"""
    name = "dsh"

    def __init__(self, status="done", tokens=None, cost=0.42, usage_missing=False):
        self._status = status
        # 契约:无 trailer = 无 usage 数据,不给 tokens/cost
        self._tokens = {"input_tokens": 1000, "output_tokens": 500} \
            if tokens is None and not usage_missing else (tokens or {})
        self._cost = 0.0 if usage_missing else cost
        self._usage_missing = usage_missing

    def run(self, packet):
        output = (USAGE_MISSING_MSG + "\nwork done") if self._usage_missing else "work done"
        return HarnessResult(status=self._status, output=output,
                             tokens=self._tokens, cost_cny=self._cost,
                             usage_missing=self._usage_missing)


def _p3_ticket(pool, task_status="pending"):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": task_status, "attempts": 0}]
    save_ticket(pool, t)
    return t


@pytest.fixture
def acceptance_ok(monkeypatch):
    # 验收复检不依赖环境里的 bash(沙箱内 git-bash 可能起不来):stub 成必过
    from orchestrator.daemon import runner as _runner
    monkeypatch.setattr(_runner, "_run_acceptance",
                        lambda cmd, cwd, timeout=600: subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="", stderr=""))


def _entries(pool):
    p = pool / "ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_dsh_ledger_entry_has_amount_tokens_calls(pool, tmp_path, acceptance_ok):
    # dsh 侧:cost 记 amount,usage trailer 的 tokens 归一为 input/output,calls=1
    proj = _git_repo(tmp_path)
    t = _p3_ticket(pool)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, StubDshAdapter(), proj, cfg=cfg,
                 consult_adapter=FakeHarness())
    entries = _entries(pool)
    assert len(entries) == 1
    e = entries[0]
    assert e["resource"] == "deepseek" and e["unit"] == "cny" and e["amount"] == 0.42
    assert e["tokens"] == {"input": 1000, "output": 500} and e["calls"] == 1
    assert ds_ticket_cost(pool, t.id) == 0.42
    assert ds_day_calls(pool) == 1


def test_k3_ledger_entry_has_tokens_calls(pool, tmp_path):
    # k3 侧与 dsh 侧同构:三字段齐全(D3 口径对齐)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p1_drafting"
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, StubAdapter(), tmp_path, cfg=cfg)
    e = _entries(pool)[0]
    assert e["resource"] == "k3" and e["unit"] == "tokens" and e["amount"] == 150
    assert e["tokens"] == {"input": 100, "output": 50} and e["calls"] == 1


def test_usage_missing_records_event_and_no_ledger(pool, tmp_path):
    # 旧版 dsh 无 usage trailer → failed + usage_missing 事件;无账不入账、不推进
    proj = _git_repo(tmp_path)
    t = _p3_ticket(pool)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    msg = advance_once(pool, t.id,
                       StubDshAdapter(status="failed", cost=0.0, usage_missing=True),
                       proj, cfg=cfg, consult_adapter=FakeHarness())
    assert msg.startswith("retry:")
    um = [e for e in read_events(pool, t.id) if e["event"] == "usage_missing"]
    assert len(um) == 1 and um[0]["task"] == "task-1"
    assert "usage trailer" in um[0]["output"]
    assert _entries(pool) == [] and ds_ticket_cost(pool, t.id) == 0.0


def test_role_path_usage_missing_event(pool, tmp_path):
    # dsh 角色(qa/release/sre)走 advance_once 通用路径,同样记 usage_missing
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p4_verifying"
    save_ticket(pool, t)
    advance_once(pool, t.id,
                 StubDshAdapter(status="failed", cost=0.0, usage_missing=True),
                 tmp_path)
    assert any(e["event"] == "usage_missing" for e in read_events(pool, t.id))
# ---------- R7 scope 越界强制检查 ----------

def _p3_scoped_task(pool, proj_path, scope, acceptance="exit 0"):
    """建 p3 工单 + 预建该任务的 worktree(模拟 dev 已领工位)。"""
    from orchestrator.daemon.worktree import ensure_worktree
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    task = {"id": "task-1", "title": "a", "acceptance_cmd": acceptance,
            "depends_on": [], "status": "pending", "attempts": 0}
    if scope is not None:
        task["scope"] = scope
    t.tasks = [task]
    save_ticket(pool, t)
    wt = ensure_worktree(proj_path, f"{t.id}-task-1")
    return t, wt


def _last_task_run_event(pool, tid):
    return [e for e in read_events(pool, tid) if e["event"] == "task_run"][-1]


def test_changed_files_enumerates_untracked_nested_files(tmp_path):
    # -uall:未跟踪目录不折叠成 `?? docs/`,否则精确 glob(如 docs/note.md)会误判越界
    from orchestrator.daemon.runner import _changed_files
    from orchestrator.daemon.worktree import ensure_worktree
    proj = _git_repo(tmp_path)
    wt = ensure_worktree(proj, "uall-check")
    (wt / "docs").mkdir()
    (wt / "docs" / "note.md").write_text("x", encoding="utf-8")
    (wt / "sneaky.py").write_text("y", encoding="utf-8")
    assert _changed_files(wt) == ["docs/note.md", "sneaky.py"]


def test_scope_violation_fails_before_acceptance(pool, tmp_path):
    """R7:harness 谎报 done 且改动越出 scope → 验收前拦下,FAIL 行置顶走重试阶梯"""
    proj = _git_repo(tmp_path)
    t, wt = _p3_scoped_task(pool, proj, ["docs/**"])
    (wt / "sneaky.py").write_text("越界改动", encoding="utf-8")   # 未跟踪,越出 docs/**
    advance_once(pool, t.id, FakeHarness(), proj)   # acceptance_cmd=exit 0 本可通过
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "pending"        # 不许 done
    assert t2.tasks[0]["attempts"] == 1
    assert "FAIL: scope 越界: sneaky.py" in t2.tasks[0]["last_error"]
    ev = _last_task_run_event(pool, t.id)
    assert ev["verify"] == "failed"
    assert ev["output"].startswith("FAIL: scope 越界: sneaky.py")
    assert "acceptance 复检失败" not in ev["output"]   # 验收未烧:越界属致命,验收前先拦


def _stub_acceptance_ok(monkeypatch):
    """复检桩:返回 exit=0(与 test_acceptance_timeout 同一 monkeypatch 先例),
    让完工路径不依赖宿主 bash(msys 段被占时 bash.exe 无法启动,见 QA 备注)。"""
    import subprocess as sp
    from orchestrator.daemon import runner
    monkeypatch.setattr(runner, "_run_acceptance",
                        lambda cmd, cwd, timeout=600: sp.CompletedProcess(cmd, 0, "", ""))


def test_scope_clean_change_passes(pool, tmp_path, monkeypatch):
    """改动都在 scope 内 → 正常走验收与完工"""
    _stub_acceptance_ok(monkeypatch)
    proj = _git_repo(tmp_path)
    t, wt = _p3_scoped_task(pool, proj, ["docs/**"])
    (wt / "docs").mkdir()
    (wt / "docs" / "note.md").write_text("界内", encoding="utf-8")
    advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "done"
    assert _last_task_run_event(pool, t.id)["verify"] == "passed"


def test_scope_catches_committed_change_via_orc_base(pool, tmp_path):
    """已提交的越界改动 status 看不到,靠 .orc-base 的 git diff 兜住;.orc-base 自身不算改动"""
    import subprocess as sp
    proj = _git_repo(tmp_path)
    t, wt = _p3_scoped_task(pool, proj, ["docs/**"])
    (wt / "sneaky.py").write_text("先改后提交", encoding="utf-8")
    sp.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)   # 连 .orc-base 一起提交
    sp.run(["git", "commit", "-m", "x"], cwd=wt, check=True, capture_output=True)
    advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "pending"
    assert "FAIL: scope 越界: sneaky.py" in t2.tasks[0]["last_error"]
    assert ".orc-base" not in t2.tasks[0]["last_error"]   # 编排器记号不是 dev 产物


def test_scope_without_base_file_degrades_to_status(pool, tmp_path):
    """无 .orc-base(旧 worktree)→ 退化为仅 git status,未跟踪越界改动仍被拦"""
    proj = _git_repo(tmp_path)
    t, wt = _p3_scoped_task(pool, proj, ["docs/**"])
    (wt / ".orc-base").unlink()
    (wt / "sneaky.py").write_text("越界", encoding="utf-8")
    advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "pending"
    assert "FAIL: scope 越界: sneaky.py" in t2.tasks[0]["last_error"]


def test_no_scope_keeps_old_behavior(pool, tmp_path, monkeypatch):
    """scope 缺省不检查:旧清单不设 scope,散件不拦,行为不变"""
    _stub_acceptance_ok(monkeypatch)
    proj = _git_repo(tmp_path)
    t, wt = _p3_scoped_task(pool, proj, None)
    (wt / "sneaky.py").write_text("无 scope 不查", encoding="utf-8")
    advance_once(pool, t.id, FakeHarness(), proj)
    assert load_ticket(pool, t.id).tasks[0]["status"] == "done"
