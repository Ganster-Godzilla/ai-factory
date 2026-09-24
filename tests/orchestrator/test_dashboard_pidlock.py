"""T-2026-0921-004 O3 先红:Dashboard 单实例 PID 锁——活锁拒启(打印占用 PID);
死锁回收启动+pid_lock_reclaimed 事件;release 只清自己的锁(不误删后启者);
锁内容含 pid+started_at。
"""
from __future__ import annotations

import json

import pytest

from orchestrator.dashboard.app import (acquire_pid_lock, release_pid_lock)
from orchestrator.daemon.events import read_events


def _write_lock(pool, pid, started="2026-09-24T00:00:00+00:00"):
    pool.mkdir(parents=True, exist_ok=True)
    (pool / ".dashboard.pid").write_text(
        json.dumps({"pid": pid, "started_at": started}), encoding="utf-8")


class TestAliveLockRefuses:
    def test_alive_occupant_refuses_with_pid(self, tmp_path):
        pool = tmp_path / "pool"
        _write_lock(pool, pid=4242)
        with pytest.raises(SystemExit) as e:
            acquire_pid_lock(pool, alive_check=lambda pid: True)
        assert "4242" in str(e.value)

    def test_refusal_does_not_touch_lock(self, tmp_path):
        pool = tmp_path / "pool"
        _write_lock(pool, pid=4242)
        with pytest.raises(SystemExit):
            acquire_pid_lock(pool, alive_check=lambda pid: True)
        # 锁原样保留(占用者的锁不被抢)
        assert json.loads((pool / ".dashboard.pid")
                          .read_text(encoding="utf-8"))["pid"] == 4242


class TestDeadLockReclaimed:
    def test_dead_occupant_reclaimed(self, tmp_path):
        pool = tmp_path / "pool"
        _write_lock(pool, pid=999999)  # 死进程(孤儿已死语义)
        acquired = acquire_pid_lock(pool, pid=1111,
                                    alive_check=lambda pid: False)
        assert acquired is True
        content = json.loads((pool / ".dashboard.pid")
                             .read_text(encoding="utf-8"))
        assert content["pid"] == 1111
        assert content["started_at"]

    def test_reclaim_event_traced(self, tmp_path):
        pool = tmp_path / "pool"
        _write_lock(pool, pid=999999)
        acquire_pid_lock(pool, pid=1111, alive_check=lambda pid: False)
        kinds = [e["event"] for e in read_events(pool, "dashboard")]
        assert "pid_lock_reclaimed" in kinds


class TestRelease:
    def test_release_own_lock(self, tmp_path):
        pool = tmp_path / "pool"
        acquire_pid_lock(pool, pid=1111, alive_check=lambda pid: False)
        release_pid_lock(pool, pid=1111)
        assert not (pool / ".dashboard.pid").exists()

    def test_release_never_deletes_others(self, tmp_path):
        """后启者的锁不被先退者误删(防退出竞态)。"""
        pool = tmp_path / "pool"
        acquire_pid_lock(pool, pid=1111, alive_check=lambda pid: False)
        # 另一实例(语义)接管锁
        _write_lock(pool, pid=2222)
        release_pid_lock(pool, pid=1111)
        assert json.loads((pool / ".dashboard.pid")
                          .read_text(encoding="utf-8"))["pid"] == 2222

    def test_release_missing_lock_is_noop(self, tmp_path):
        release_pid_lock(tmp_path / "pool", pid=1111)  # 不炸
