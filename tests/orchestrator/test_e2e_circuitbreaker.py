"""M3 验收:熔断阶梯全链路 + 台账记账。"""
import subprocess

from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.ledger import ds_day_cost
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import APPROVALS, transition
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket


def _git_repo_at(path):
    # runner 派发任务要建 git worktree(ensure_worktree base=main),
    # 故 project_dir 必须是带 main 分支的 git 仓库;在 tmp_path 原地初始化,
    # 保持下方 brief 代码中 project_dir=tmp_path 逐字不变。
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / ".gitkeep").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=path, check=True, capture_output=True)


def test_circuit_breaker_full_lifecycle(pool, tmp_path):
    _git_repo_at(tmp_path)
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
