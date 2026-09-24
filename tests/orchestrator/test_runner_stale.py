"""T-2026-0921-004 O2 先红:runner 存点 stale 降级——角色运行期 boss 点击
(盘上被外部改写)→ runner 存点被 CAS 拒 → advance_once 捕获发 stale_aborted
事件+弃写不续跑;boss 的写入零污染;异常不外溢。
"""
from __future__ import annotations

import subprocess

from orchestrator.adapters.fake import FakeHarness
from orchestrator.adapters.base import HarnessResult, TaskPacket
from orchestrator.daemon.events import read_events
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


def _p3_ticket(pool, tmp_path):
    _git_repo_at(tmp_path)
    t = new_ticket(pool, project="p", summary="s")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, load_ticket(pool, t.id), "p1_drafting", actor="boss")
    t2 = load_ticket(pool, t.id)
    t2.tasks = [{"id": "task-1", "title": "a", "acceptance_cmd": "exit 0",
                 "depends_on": [], "status": "pending", "attempts": 0}]
    t2.state = "p3_running"
    save_ticket(pool, t2)
    return t


class BossClickHarness(FakeHarness):
    """运行期模拟 boss 点击:另一对象(另一进程语义)改写盘上车票。"""

    def __init__(self, pool, ticket_id):
        super().__init__()
        self._pool, self._tid = pool, ticket_id

    def run(self, packet: TaskPacket) -> HarnessResult:
        ext = load_ticket(self._pool, self._tid)
        transition(self._pool, ext, "suspended", actor="boss",
                   reason="boss 手动挂起", reason_code="manual")
        return super().run(packet)


class TestRunnerStaleDegrade:
    def test_stale_mid_run_aborts_loudly(self, pool, tmp_path):
        t = _p3_ticket(pool, tmp_path)
        msg = advance_once(pool, t.id, BossClickHarness(pool, t.id), tmp_path)
        # 异常不外溢:返回串明示 stale 中止
        assert "stale" in msg

    def test_boss_write_zero_pollution(self, pool, tmp_path):
        t = _p3_ticket(pool, tmp_path)
        advance_once(pool, t.id, BossClickHarness(pool, t.id), tmp_path)
        after = load_ticket(pool, t.id)
        # boss 的挂起原样在盘上;runner 的 tasks 进度没有覆盖回去
        assert after.state == "suspended"
        assert after.tasks[0]["status"] == "pending"

    def test_stale_aborted_event_traced(self, pool, tmp_path):
        t = _p3_ticket(pool, tmp_path)
        advance_once(pool, t.id, BossClickHarness(pool, t.id), tmp_path)
        kinds = [e["event"] for e in read_events(pool, t.id)]
        assert "stale_aborted" in kinds

    def test_normal_run_without_race_unaffected(self, pool, tmp_path):
        """无竞态的正常跑:任务照样 done(降级只拦真竞态)。"""
        t = _p3_ticket(pool, tmp_path)
        advance_once(pool, t.id, FakeHarness(), tmp_path)
        assert load_ticket(pool, t.id).tasks[0]["status"] == "done"
