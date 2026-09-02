"""T-2026-0902-010 S3:runner 三处接线(dev/consult/五角色)经 _run_with_watchdog
包装 + killed→timeout 判负改写 + 全角色路径冒烟 + 父活语义回归。适配器文件零改动。

冒烟形态:monkeypatch watchdog.guard 为记录器,逐路径断言调用均经包装
(role/task_id/timeout=packet.timeout);killed→timeout 用记录器置 killed 验证改写;
父活语义回归用真实 guard + 不起子进程的 stub 证透传零副作用。
D5:断言失败一律先打印 `FAIL: <子句>`。
"""
import subprocess
import sys
from pathlib import Path

import pytest

# 裸 `pytest` 不带 cwd 上 sys.path,兜底插仓根与 tests/orchestrator(_git_repo 先例)
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests" / "orchestrator"))

from orchestrator.adapters.base import HarnessAdapter, HarnessResult
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon import runner, watchdog
from orchestrator.daemon.events import read_events
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket

from test_routing import _git_repo  # noqa: E402


@pytest.fixture
def pool(tmp_path):
    p = tmp_path / "pool"
    (p / "tickets").mkdir(parents=True)
    return p


@pytest.fixture(autouse=True)
def _bypass_gate_by_default(monkeypatch):
    """与 tests/orchestrator/conftest.py 同款:本文件主题是接线而非门禁。"""
    from orchestrator.daemon import statemachine as sm
    monkeypatch.setattr(sm, "_enforce_gate", lambda *a, **k: None)


def _check(cond, clause):
    if not cond:
        print(f"FAIL: {clause}")
    assert cond, clause


class StubAdapter(HarnessAdapter):
    name = "claude_code"

    def __init__(self, status="done"):
        self._status = status

    def run(self, packet):
        return HarnessResult(status=self._status, output=f"stub:{packet.role}")


@pytest.fixture
def guard_recorder(monkeypatch):
    """替换 watchdog.guard 为记录器:不真打补丁,只记调用参数;killed 可按用例置位。"""
    calls = []
    state = {"killed": False}

    class RecGuard:
        def __init__(self, pool, ticket, role=None, task_id=None,
                     timeout=300, grace=None):
            calls.append({"ticket": getattr(ticket, "id", ticket), "role": role,
                          "task_id": task_id, "timeout": timeout})
            self.killed = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.killed = state["killed"]
            return False

    monkeypatch.setattr(watchdog, "guard", RecGuard)
    return calls, state


def _p3_ticket(pool, attempts=0):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": attempts}]
    save_ticket(pool, t)
    return t


def _stub_acceptance_ok(monkeypatch):
    monkeypatch.setattr(runner, "_run_acceptance",
                        lambda cmd, cwd, timeout=600: subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="", stderr=""))


# ---------------- 三处接线 + 全角色路径冒烟 ----------------

ROLE_STATES = {
    "p1_drafting": "pm", "p2_designing": "architect", "p4_verifying": "qa",
    "p5_releasing": "release", "monitoring": "sre",
}


def test_five_role_paths_wrapped(pool, tmp_path, guard_recorder):
    """五角色路径全部经 guard 包装:role 对、task_id=None、墙钟=packet.timeout。"""
    calls, _ = guard_recorder
    for state, role in ROLE_STATES.items():
        calls.clear()
        t = new_ticket(pool, project="p", summary="x")
        t.state = state
        save_ticket(pool, t)
        advance_once(pool, t.id, StubAdapter(), tmp_path)
        _check(len(calls) == 1, f"{state} 恰好一次 guard 包装")
        _check(calls[0]["role"] == role, f"{state} guard role={role}")
        _check(calls[0]["task_id"] is None, f"{state} guard task_id 为 None")
        expected = runner.ROLE_TIMEOUT.get(role, 1800)
        _check(calls[0]["timeout"] == expected,
               f"{state} 墙钟=packet.timeout({expected})")


def test_dev_task_wrapped(pool, tmp_path, guard_recorder, monkeypatch):
    """dev 任务调用经 guard:role=dev、task_id=任务 id、墙钟=packet.timeout。"""
    calls, _ = guard_recorder
    _stub_acceptance_ok(monkeypatch)
    proj = _git_repo(tmp_path)
    t = _p3_ticket(pool)
    advance_once(pool, t.id, FakeHarness(), proj)
    _check(len(calls) == 1, "dev 恰好一次 guard 包装")
    _check(calls[0]["role"] == "dev", "dev guard role=dev")
    _check(calls[0]["task_id"] == "task-1", "dev guard task_id=任务 id")
    _check(calls[0]["timeout"] == 1800, "dev 墙钟=packet.timeout(缺省 1800)")


def test_consult_wrapped(pool, tmp_path, guard_recorder):
    """会诊调用经 guard:role=architect、task_id=会诊任务 id。"""
    calls, _ = guard_recorder
    proj = _git_repo(tmp_path)
    t = _p3_ticket(pool, attempts=3)  # attempts=MAX_RETRY → 下一步会诊
    msg = advance_once(pool, t.id, FakeHarness(script=["failed"]), proj,
                       consult_adapter=FakeHarness())
    _check(msg.startswith("consult:"), "走到会诊阶梯")
    pairs = [(c["role"], c["task_id"]) for c in calls]
    _check(("dev", "task-1") in pairs, "dev 调用经 guard")
    _check(("architect", "task-1") in pairs, "会诊调用经 guard(role=architect)")


# ---------------- killed→timeout 判负改写 ----------------

def test_killed_rewrites_dev_result_to_timeout(pool, tmp_path, guard_recorder):
    """helper 杀组(guard.killed)→ dev 结果改写 timeout:任务不 done、走重试阶梯、
    事件与 last_error 留痕 watchdog_killed。"""
    _, state = guard_recorder
    state["killed"] = True
    proj = _git_repo(tmp_path)
    t = _p3_ticket(pool)
    msg = advance_once(pool, t.id, FakeHarness(), proj)  # harness 谎报 done
    t2 = load_ticket(pool, t.id)
    _check(t2.tasks[0]["status"] == "pending", "killed 后任务不得 done")
    _check(t2.tasks[0]["attempts"] == 1, "计一次尝试")
    _check("watchdog_killed" in t2.tasks[0]["last_error"],
           "last_error 留痕 watchdog_killed")
    ev = [e for e in read_events(pool, t.id) if e["event"] == "task_run"][-1]
    _check(ev["status"] == "timeout", "task_run 事件按 timeout 判负(与适配器自报同值)")
    _check(msg.startswith("retry:"), "失败沿既有重试阶梯走")


def test_killed_rewrites_role_result_to_timeout(pool, tmp_path, guard_recorder):
    """角色路径 killed→timeout 判负:挂起 + role_run 事件 status=timeout。"""
    _, state = guard_recorder
    state["killed"] = True
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p4_verifying"
    save_ticket(pool, t)
    msg = advance_once(pool, t.id, StubAdapter(), tmp_path)
    t2 = load_ticket(pool, t.id)
    _check(t2.state == "suspended", "角色 killed→timeout 判负挂起")
    _check(msg == "role:qa:timeout", "返回串按 timeout 判负")
    ev = [e for e in read_events(pool, t.id) if e["event"] == "role_run"][-1]
    _check(ev["status"] == "timeout", "role_run 事件 status=timeout")
    _check("watchdog_killed" in ev["output"], "事件 output 留痕 watchdog_killed")


def test_killed_idempotent_with_adapter_self_report(pool, tmp_path, guard_recorder):
    """适配器自报 timeout 时 killed 改写幂等:status 不变、原输出不二次包装。"""
    _, state = guard_recorder
    state["killed"] = True
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p4_verifying"
    save_ticket(pool, t)
    advance_once(pool, t.id, StubAdapter(status="timeout"), tmp_path)
    ev = [e for e in read_events(pool, t.id) if e["event"] == "role_run"][-1]
    _check(ev["status"] == "timeout", "自报 timeout 保持 timeout")
    _check(ev["output"] == "stub:qa", "自报 timeout 输出原样,不二次包装")


# ---------------- 父活语义回归(真实 guard) ----------------

def test_parent_alive_real_guard_role_passthrough(pool, tmp_path):
    """父活+准时收工:真实 guard + 不起子进程的 stub → 结果透传、状态推进、零事件。"""
    t = new_ticket(pool, project="p", summary="x")
    transition_target = "p1_drafting"
    t.state = transition_target
    save_ticket(pool, t)
    msg = advance_once(pool, t.id, StubAdapter(), tmp_path)
    _check(msg == "role:pm:done", "真实 guard 透传 adapter 结果")
    _check(load_ticket(pool, t.id).state == "p1_proposed", "状态照常推进")
    _check(not [e for e in read_events(pool, t.id)
                if e["event"] == "watchdog_killed"], "父活准时收工零 watchdog 事件")


def test_parent_alive_real_guard_dev_done(pool, tmp_path, monkeypatch):
    """父活 dev 完工:真实 guard 下任务照常 done、验收照常跑、零 watchdog 事件。"""
    _stub_acceptance_ok(monkeypatch)
    proj = _git_repo(tmp_path)
    t = _p3_ticket(pool)
    msg = advance_once(pool, t.id, FakeHarness(), proj)
    _check(msg == "task:task-1:done", "真实 guard 下 dev 照常完工")
    _check(load_ticket(pool, t.id).tasks[0]["status"] == "done", "任务落盘 done")
    _check(not [e for e in read_events(pool, t.id)
                if e["event"] == "watchdog_killed"], "零 watchdog 事件")
