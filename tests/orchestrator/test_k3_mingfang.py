"""T-2026-0902-009 B5:k3 水位闸观察期 warn-only(与 DS 明放同款,mingfang_mode 控制)。"""
import subprocess

from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.ledger import append_ledger
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import transition
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket


def _git_repo_at(path):
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / ".gitkeep").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", ".gitkeep"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=path, check=True, capture_output=True)


def _ticket_in_p3(pool, tmp_path):
    _git_repo_at(tmp_path)
    t = new_ticket(pool, project="p", summary="x")
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
    # 水位恒超线:预算 0 + 台账已有 k3 tokens
    append_ledger(pool, "k3", 5, "tokens", t.id, "pm", "k3")
    return t.id


def _cfg(mingfang):
    return {"budgets": {"k3_week_token_budget": 0, "ds_daily_cny": 10**9,
                        "mingfang_mode": mingfang, "ds_est_call_cny": 0.05}}


def test_over_budget_mingfang_warns_but_consults(pool, tmp_path):
    tid = _ticket_in_p3(pool, tmp_path)
    dev = FakeHarness(script=["failed", "failed", "failed", "done"])
    for _ in range(3):   # 第 3 次失败触发 consult 分支
        advance_once(pool, tid, dev, tmp_path, cfg=_cfg(True), consult_adapter=FakeHarness())
    t = load_ticket(pool, tid)
    assert t.state == "p3_running"          # 未挂起
    assert t.tasks[0].get("consulted") is True
    evts = [e["event"] for e in read_events(pool, tid)]
    assert "budget_warn" in evts


def test_over_budget_hard_gate_suspends(pool, tmp_path):
    tid = _ticket_in_p3(pool, tmp_path)
    dev = FakeHarness(script=["failed", "failed", "failed"])
    out = None
    for _ in range(3):
        out = advance_once(pool, tid, dev, tmp_path, cfg=_cfg(False),
                           consult_adapter=FakeHarness())
    t = load_ticket(pool, tid)
    assert t.state == "suspended"
    assert "配额超线" in (out or "")
