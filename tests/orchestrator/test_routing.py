from orchestrator.adapters import get_adapter
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
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
    advance_once(pool, t.id, h, proj)
    t2 = load_ticket(pool, t.id)
    # 一次 advance 只派一个 ready 任务;task-2 依赖未满足
    assert t2.tasks[0]["status"] == "done"
    assert t2.tasks[1]["status"] == "pending"
    assert t2.state == "p3_running"
    # 任务包发到了该任务的 worktree
    assert "orc-task-1" in str(h.received[0].workdir) or "task-1" in str(h.received[0].workdir)
    # worktree 名按工单命名空间隔离,跨工单不串
    assert t.id in str(h.received[0].workdir)


def _write_tasks_yaml(proj, tid, body):
    # T-2026-0830-001 起:tasks.yaml 在工单文件夹 02_设计文档/ 下
    d = proj / "document" / "business" / f"{tid}-测试需求" / "02_设计文档"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.yaml").write_text(body, encoding="utf-8", newline="\n")


def test_p3_lazy_loads_tasks_yaml(pool, tmp_path):
    # 架构师产物 docs/specs/<tid>-tasks.yaml 存在时,p3 首次推进应装载进 ticket.tasks
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    save_ticket(pool, t)  # tasks 为空
    _write_tasks_yaml(proj, t.id, (
        "- id: task-1\n  title: a\n  acceptance_cmd: 'true'\n  depends_on: []\n"
        "- id: task-2\n  title: b\n  acceptance_cmd: 'true'\n  depends_on: [task-1]\n"
    ))
    h = FakeHarness()
    advance_once(pool, t.id, h, proj)
    t2 = load_ticket(pool, t.id)
    assert len(t2.tasks) == 2
    assert t2.tasks[0]["status"] == "done"      # task-1 被派发且完成
    assert t2.tasks[1]["status"] == "pending"   # task-2 依赖未满足
    assert t2.state == "p3_running"
    assert "task-1" in str(h.received[0].workdir)
    assert t.id in str(h.received[0].workdir)


def test_p3_bad_tasks_yaml_suspends(pool, tmp_path):
    # 畸形 YAML 不得裸抛:工单应挂起,reason 说明装载失败
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    save_ticket(pool, t)
    _write_tasks_yaml(proj, t.id, "{{{[not yaml")
    advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    assert t2.resume_state == "p3_running"
    assert any(e["event"] == "suspended" and "装载失败" in e["reason"]
               for e in read_events(pool, t.id))


def test_p3_no_tasks_yaml_keeps_auto_p4(pool, tmp_path):
    # 无 tasks.yaml 时维持现状:空 tasks → auto p4,不派发任何任务
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    save_ticket(pool, t)
    h = FakeHarness()
    msg = advance_once(pool, t.id, h, proj)
    assert msg == "auto: p4_verifying"
    assert load_ticket(pool, t.id).state == "p4_verifying"
    assert h.received == []


def test_failed_task_run_event_carries_output(pool, tmp_path):
    # 失败任务的 task_run 事件必须带 output,排查不靠猜
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": "task-1", "title": "a", "acceptance_cmd": "true", "depends_on": [],
         "status": "pending", "attempts": 0},
    ]
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(script=["failed"]), proj)
    ev = [e for e in read_events(pool, t.id) if e["event"] == "task_run"]
    assert ev and ev[-1]["status"] == "failed"
    assert "output" in ev[-1] and "fake" in ev[-1]["output"]


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


def test_deadlocked_tasks_suspend(pool, tmp_path):
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [
        {"id": "a", "title": "x", "acceptance_cmd": "true", "depends_on": ["gone"],
         "status": "pending", "attempts": 0},
    ]
    save_ticket(pool, t)
    advance_once(pool, t.id, FakeHarness(), proj)
    t2 = load_ticket(pool, t.id)
    assert t2.state == "suspended"
    from orchestrator.daemon.events import read_events
    assert any("依赖" in str(e.get("reason", "")) for e in read_events(pool, t.id))


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
    advance_once(pool, t.id, h, proj, cfg=cfg, consult_adapter=consult)      # 会诊后再失败 → 任务判负
    t2 = load_ticket(pool, t.id)
    # 任务判负制(spec §5.2):会诊≤1,会诊后再败 → 任务标 failed;判负本身不挂工单
    assert t2.tasks[0]["status"] == "failed"
    assert t2.consult_count == 1             # consult_count 计判负任务数,非会诊调用次数
    # 单任务工单:判负后无 ready 且非全 done → 整单 circuit_exhausted
    assert t2.state == "suspended"
    codes = [e.get("reason_code") for e in read_events(pool, t.id) if e["event"] == "suspended"]
    assert codes == ["circuit_exhausted"]


def test_single_task_failure_suspends_circuit_exhausted(pool, tmp_path):
    """单任务工单:会诊后仍失败判负 → 无 ready 可派,整单 circuit_exhausted"""
    proj = _git_repo(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 3,
                "consulted": True}]
    save_ticket(pool, t)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    msg = advance_once(pool, t.id, FakeHarness(script=["failed"]), proj,
                       cfg=cfg, consult_adapter=FakeHarness())
    assert msg == "suspend: 任务判负"
    t2 = load_ticket(pool, t.id)
    assert t2.tasks[0]["status"] == "failed"
    assert t2.state == "suspended"
    evts = [e for e in read_events(pool, t.id) if e["event"] == "suspended"]
    assert [e.get("reason_code") for e in evts] == ["circuit_exhausted"]
    assert "任务判负" in evts[0]["reason"]


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


def _p3_ticket_with_task(pool):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    return t


def test_cfg_models_override_dev_model(pool, tmp_path):
    # Finding S4:cfg["models"][role] 优先于 ROLE_MODEL 兜底
    proj = _git_repo(tmp_path)
    t = _p3_ticket_with_task(pool)
    h = FakeHarness()
    cfg = {"models": {"dev": "glm-5.3-flash"},
           "budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, h, proj, cfg=cfg)
    assert h.received[0].model == "glm-5.3-flash"


def test_no_cfg_falls_back_to_role_model(pool, tmp_path):
    # Finding S4:无 cfg 时维持 ROLE_MODEL 兜底
    proj = _git_repo(tmp_path)
    t = _p3_ticket_with_task(pool)
    h = FakeHarness()
    advance_once(pool, t.id, h, proj)
    assert h.received[0].model == "deepseek-v4-flash"


def test_cfg_models_override_role_model(pool, tmp_path):
    # Finding S4:非 p3 角色(advance_once 直发)同样走 cfg["models"]
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p4_verifying"
    save_ticket(pool, t)
    h = FakeHarness()
    cfg = {"models": {"qa": "glm-5.3-flash"},
           "budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 10**9}}
    advance_once(pool, t.id, h, tmp_path, cfg=cfg)
    assert h.received[0].model == "glm-5.3-flash"
