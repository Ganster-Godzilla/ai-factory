"""T-2026-0902-010 S3:父活语义回归——runner 经 _run_with_watchdog 包装后,
父活+准时收工路径行为与接线前完全一致(真实 guard,不 mock)。

与 tests/test_runner_watchdog.py 分工:那边用记录器 guard 证接线/改写,
这边用真实 guard 证透传零副作用——不杀组、不改写、不落 watchdog 事件。
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
from orchestrator.daemon import runner
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
    """与 tests/orchestrator/conftest.py 同款:本文件主题是父活回归而非门禁。"""
    from orchestrator.daemon import statemachine as sm
    monkeypatch.setattr(sm, "_enforce_gate", lambda *a, **k: None)


def _check(cond, clause):
    if not cond:
        print(f"FAIL: {clause}")
    assert cond, clause


class StubAdapter(HarnessAdapter):
    name = "claude_code"

    def run(self, packet):
        return HarnessResult(status="done", output=f"stub:{packet.role}")


def _p3_ticket(pool):
    t = new_ticket(pool, project="p", summary="x")
    t.state = "p3_running"
    t.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                "depends_on": [], "status": "pending", "attempts": 0}]
    save_ticket(pool, t)
    return t


def _stub_acceptance_ok(monkeypatch):
    monkeypatch.setattr(runner, "_run_acceptance",
                        lambda cmd, cwd, timeout=600: subprocess.CompletedProcess(
                            args=[], returncode=0, stdout="", stderr=""))


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
