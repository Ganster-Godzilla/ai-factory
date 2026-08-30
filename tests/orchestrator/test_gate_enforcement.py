"""G4:闸门接线(T-2026-0829-001 设计 M4)——真实 enforcement 测试。
conftest 默认把 _enforce_gate 旁路(隔离既有用例),本文件测真闸门。"""
import pytest

from orchestrator.daemon.statemachine import IllegalTransition, transition
from orchestrator.daemon.ticket import new_ticket, save_ticket


def _new(pool):
    return new_ticket(pool, project="p", summary="接线测试")


def _write(proj, rel, text):
    p = proj / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_gated_edge_requires_project_dir(pool):
    t = _new(pool)
    t.state = "p0_proposed"
    save_ticket(pool, t)
    with pytest.raises(IllegalTransition, match="project_dir"):
        transition(pool, t, "p1_drafting", actor="boss")   # 新单+门禁边+缺 project_dir


def test_gated_edge_missing_artifact_blocks(pool, tmp_path):
    t = _new(pool)
    t.state = "p0_proposed"
    save_ticket(pool, t)
    with pytest.raises(IllegalTransition) as e:
        transition(pool, t, "p1_drafting", actor="boss", project_dir=tmp_path)
    assert "提案.md" in str(e.value)


def test_gated_edge_complete_passes(pool, tmp_path):
    t = _new(pool)
    _write(tmp_path, f"document/business/{t.id}-测试需求/00_提案/提案.md",
           "# 提案\n## 问题\nx\n## 方向\nx\n## 范围\nx\n## 不做\nx\n")
    transition(pool, t, "p0_proposed", actor="pm", project_dir=tmp_path)
    assert t.state == "p0_proposed"


def test_legacy_ticket_no_project_dir_needed(pool):
    t = _new(pool)
    t.created_at = None          # 存量单:不要求 project_dir,不校验
    t.state = "p0_proposed"
    save_ticket(pool, t)
    transition(pool, t, "p1_drafting", actor="boss")
    assert t.state == "p1_drafting"


def test_non_gated_edge_no_enforcement(pool):
    t2 = _new(pool)
    transition(pool, t2, "p0_proposed", actor="pm")   # 提交边非门禁(挂审批边界)
    assert t2.state == "p0_proposed"


# ---------- runner 自动边:gate 失败转 suspend(artifact_missing) ----------

def test_runner_gate_failure_suspends(pool, tmp_path):
    """run_dev_tasks 全任务 done 触发 p3→p4 自动边;verify 留痕缺失 → 挂起+事件。"""
    import subprocess
    from orchestrator.daemon.runner import run_dev_tasks
    from orchestrator.daemon.events import read_events
    from orchestrator.daemon.ticket import load_ticket
    from orchestrator.adapters.fake import FakeHarness

    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=proj, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    (proj / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=proj, check=True,
                   capture_output=True)

    t = _new(pool)
    t.state = "p3_running"
    # 任务全 done 但有 acceptance_cmd 且无 verify 留痕 → P3 门禁必拦
    t.tasks = [{"id": "g1", "title": "x", "status": "done", "attempts": 1,
                "depends_on": [], "acceptance_cmd": "exit 0"}]
    save_ticket(pool, t)
    out = run_dev_tasks(pool, t, FakeHarness(), proj,
                        cfg={"budgets": {"k3_week_token_budget": 10**9,
                                         "ds_daily_cny": 10**9}})
    assert "artifact" in out or "suspend" in out
    assert load_ticket(pool, t.id).state == "suspended"
    evs = [e for e in read_events(pool, t.id) if e["event"] == "gate_failed"]
    assert evs and evs[-1].get("missing")


def test_verify_persisted_on_task(pool, tmp_path):
    """验收复检后 task[verify] 落盘 passed/failed(设计 D6)。"""
    import subprocess as sp
    from orchestrator.daemon.runner import run_dev_tasks
    from orchestrator.daemon.ticket import load_ticket
    from orchestrator.adapters.fake import FakeHarness

    proj = tmp_path / "proj"
    proj.mkdir()
    sp.run(["git", "init", "-b", "main"], cwd=proj, check=True, capture_output=True)
    sp.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    sp.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    (proj / "f.txt").write_text("x", encoding="utf-8")
    sp.run(["git", "add", "."], cwd=proj, check=True)
    sp.run(["git", "commit", "-m", "i"], cwd=proj, check=True, capture_output=True)

    t = _new(pool)
    t.state = "p3_running"
    t.tasks = [{"id": "g1", "title": "x", "status": "pending", "attempts": 0,
                "depends_on": [], "acceptance_cmd": "exit 1"}]   # 验收必挂
    save_ticket(pool, t)
    run_dev_tasks(pool, t, FakeHarness(), proj,
                  cfg={"budgets": {"k3_week_token_budget": 10**9,
                                   "ds_daily_cny": 10**9}})
    task = load_ticket(pool, t.id).tasks[0]
    assert task.get("verify") == "failed"


def test_gate_failed_structured_fails(pool, tmp_path):
    # 评审 R3-3:GateFailed 结构化携带 fails,不靠字符串嗅探
    from orchestrator.daemon.statemachine import GateFailed
    t = _new(pool)
    t.state = "p0_proposed"
    save_ticket(pool, t)
    with pytest.raises(GateFailed) as e:
        transition(pool, t, "p1_drafting", actor="boss", project_dir=tmp_path)
    assert e.value.fails and any("提案.md" in f for f in e.value.fails)
