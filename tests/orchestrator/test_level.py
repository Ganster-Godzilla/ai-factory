"""任务分级(L1/L2/L3)测试 — T-2026-0829-006。

覆盖:level 字段与建单(R1)、状态机 L3 条件边(R2)、审批解析(R3)、
熔断参数按级别(R4)、门禁裁剪(R5 直测 check_gate 部分)。
设计:document/business/T-2026-0829-006-分级实施/02_设计文档/design.md
"""
from __future__ import annotations

import pytest

from orchestrator.daemon.circuitbreaker import next_action
from orchestrator.daemon.statemachine import (
    IllegalTransition, approval_target, transition,
)
from orchestrator.daemon.ticket import Ticket, load_ticket, new_ticket, save_ticket


def _ticket(pool, *, level=None, state="draft", type="feature", created_at="2026-09-08T00:00:00+00:00"):
    """构造一张新工单(走 new_ticket 留事件);level=None 模拟存量无字段。"""
    t = new_ticket(pool, "quant-lab", "分级测试单", level=level or "L1", type=type)
    t.state = state
    if level is None:   # 模拟存量 yaml:删字段后写盘
        t.level = "L1"
        save_ticket(pool, t)
        p = pool / "tickets" / f"{t.id}.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("level: L1\n", ""), encoding="utf-8")
    else:
        save_ticket(pool, t)
    return t


# ── R1:字段与建单 ────────────────────────────────────────────────────────────

def test_level_default_l1_on_legacy_load(pool):
    """存量 yaml 无 level 字段 → load 兜底 L1。"""
    t = _ticket(pool, level=None)
    assert load_ticket(pool, t.id).level == "L1"


def test_level_validate_rejects_out_of_domain(pool):
    t = _ticket(pool, level="L2")
    t.level = "L4"
    with pytest.raises(ValueError, match="level"):
        save_ticket(pool, t)


def test_new_ticket_level_param_and_default(pool):
    assert _ticket(pool, level="L3").level == "L3"
    assert _ticket(pool, level="L2").level == "L2"
    t = new_ticket(pool, "quant-lab", "缺省单")
    assert t.level == "L1"


# ── R2:状态机 L3 条件边 ─────────────────────────────────────────────────────

def test_l3_fast_edge_p0_to_p3_queued(pool):
    t = _ticket(pool, level="L3", state="p0_proposed")
    transition(pool, t, "p3_queued", actor="boss")
    assert t.state == "p3_queued"


def test_l1_cannot_take_fast_edges(pool):
    t = _ticket(pool, level="L1", state="p0_proposed")
    with pytest.raises(IllegalTransition, match="L3"):
        transition(pool, t, "p3_queued", actor="boss")
    t2 = _ticket(pool, level="L2", state="p0_proposed")
    with pytest.raises(IllegalTransition, match="L3"):
        transition(pool, t2, "p3_queued", actor="boss")


def test_l3_release_to_done_marks_monitoring_skipped(pool):
    from orchestrator.daemon.events import read_events
    t = _ticket(pool, level="L3", state="p5_releasing")
    transition(pool, t, "done", actor="release")
    assert t.state == "done"
    ev = [e for e in read_events(pool, t.id) if e.get("to") == "done"][-1]
    assert ev.get("monitoring_skipped") is True


def test_l1_release_to_done_rejected(pool):
    t = _ticket(pool, level="L1", state="p5_releasing")
    with pytest.raises(IllegalTransition):
        transition(pool, t, "done", actor="release")


# ── R3:审批解析 ──────────────────────────────────────────────────────────────

def test_approval_target_level_aware(pool):
    l3 = _ticket(pool, level="L3", state="p0_proposed")
    assert approval_target(l3) == "p3_queued"
    l1 = _ticket(pool, level="L1", state="p0_proposed")
    assert approval_target(l1) == "p1_drafting"
    l2 = _ticket(pool, level="L2", state="p0_proposed")
    assert approval_target(l2) == "p1_drafting"
    # 其余审批态不受 level 影响
    l3_p1 = _ticket(pool, level="L3", state="p1_proposed")
    assert approval_target(l3_p1) == "p2_designing"
    # 非审批态
    l3_run = _ticket(pool, level="L3", state="p3_running")
    assert approval_target(l3_run) is None


# ── R4:熔断参数按级别 ────────────────────────────────────────────────────────

def test_next_action_l3_tighter_circuit():
    task = {"id": "S1", "attempts": 0}
    assert next_action(task, "L3") == "retry"
    task["attempts"] = 1
    assert next_action(task, "L3") == "retry"
    task["attempts"] = 2
    # L3 免会诊:达上限直接 suspend,不出现 consult
    assert next_action(task, "L3") == "suspend"
    task["attempts"] = 3
    assert next_action(task, "L3") == "suspend"


def test_next_action_l1_unchanged():
    task = {"id": "S1", "attempts": 2}
    assert next_action(task) == "retry"          # ≤3 仍可 retry
    task["attempts"] = 3
    assert next_action(task) == "consult"        # L1 保留会诊
    task["consulted"] = True
    assert next_action(task) == "suspend"
    # 显式 L2 与 L1 同行为(本单 L2 不裁剪)
    task2 = {"id": "S1", "attempts": 3}
    assert next_action(task2, "L2") == "consult"


# ── T-2026-0908-003 R1:runner level→驾驶员注入 ────────────────────────────────

def test_driver_for_level_mapping():
    from orchestrator.daemon.runner import _driver_for_level
    t = Ticket(id="T-2026-0908-099", type="feature", project="x",
                   state="draft", owner_role="pm")
    t.level = "L3"
    assert _driver_for_level(t) == "k2.6"
    t.level = "L2"
    assert _driver_for_level(t) == "k2.6"
    t.level = "L1"
    assert _driver_for_level(t) is None
    # 存量无 level 属性对象:getattr 兜底 L1 → None
    class Legacy: pass
    assert _driver_for_level(Legacy()) is None


def test_dispatch_injects_driver_model(pool, tmp_path, monkeypatch):
    """端到端(T-2026-0908-003 R1):_dispatch_task 按 level 注入 packet.model;
    L1 回落 _model_for(cfg 缺省 → ROLE_MODEL['dev']=deepseek-v4-flash)。"""
    from orchestrator.daemon import runner
    from orchestrator.adapters.base import HarnessResult
    seen = {}

    def fake_run(pool_, ticket_, adapter_, packet, role, **kw):
        seen["model"] = packet.model
        return HarnessResult(status="done", output="ok")

    monkeypatch.setattr(runner, "ensure_worktree", lambda *a, **k: tmp_path)
    monkeypatch.setattr(runner, "_run_with_watchdog", fake_run)

    l3 = _ticket(pool, level="L3", state="p3_running")
    l3.tasks = [{"id": "S1", "title": "x", "status": "pending", "attempts": 0,
                 "acceptance_cmd": "echo ok"}]
    runner._dispatch_task(pool, l3, l3.tasks[0], object(), tmp_path, None, None)
    assert seen["model"] == "k2.6"

    l1 = _ticket(pool, level="L1", state="p3_running")
    l1.tasks = [{"id": "S1", "title": "x", "status": "pending", "attempts": 0,
                 "acceptance_cmd": "echo ok"}]
    runner._dispatch_task(pool, l1, l1.tasks[0], object(), tmp_path, None, None)
    assert seen["model"] == "deepseek-v4-flash"   # L1 零变化(现默认)
