"""T-2026-0921-004 O3 先红:Dashboard 单实例 PID 锁——活锁拒启(打印占用 PID);
死锁回收启动+pid_lock_reclaimed 事件;release 只清自己的锁(不误删后启者);
锁内容含 pid+started_at。

T-2026-1104-001 G2:Windows 僵尸判死活判——OpenProcess 可打开≠活着,
须 GetExitCodeProcess==STILL_ACTIVE(259);非 259/调用失败判死,回收不误拒。
"""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

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

    def test_same_pid_reentry_is_idempotent(self, tmp_path):
        """同进程重入=同一实例(进程内二次启动/冒烟复跑),放行非孤儿。"""
        pool = tmp_path / "pool"
        _write_lock(pool, pid=4242)
        assert acquire_pid_lock(pool, pid=4242,
                                alive_check=lambda pid: True) is True

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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ctypes 语义")
class TestWindowsRealLiveness:
    """T-2026-1104-001:OpenProcess 可打开僵尸对象 ≠ 活着;
    真活判 = OpenProcess 成功 + GetExitCodeProcess==STILL_ACTIVE(259)。"""

    def _mock_kernel32(self, open_ok=True, exit_code=259, get_exit_ok=True):
        k = MagicMock()
        k.OpenProcess.return_value = 1234 if open_ok else None
        def _get_exit(h, p):
            if not get_exit_ok:
                return 0
            # DWORD buffer:写入给定退出码
            p._obj.value = getattr(self, "_exit_code", 259)
            return 1
        k.GetExitCodeProcess.side_effect = _get_exit
        k.CloseHandle.return_value = 1
        return k

    def test_zombie_process_judged_dead_and_reclaimed(self, tmp_path):
        """僵尸(可打开但退出码非 259)→ 判死,回收锁不拒启。"""
        self._exit_code = 0
        k = self._mock_kernel32(open_ok=True, get_exit_ok=True)
        with patch("ctypes.windll.kernel32", k):
            from orchestrator.dashboard.app import _pid_alive_default
            assert _pid_alive_default(9999) is False
        pool = tmp_path / "pool"
        _write_lock(pool, pid=9999)
        with patch("ctypes.windll.kernel32", k):
            acquired = acquire_pid_lock(pool, pid=1111)
        assert acquired is True
        assert json.loads((pool / ".dashboard.pid")
                          .read_text(encoding="utf-8"))["pid"] == 1111
        kinds = [e["event"] for e in read_events(pool, "dashboard")]
        assert "pid_lock_reclaimed" in kinds

    def test_alive_process_still_active_refuses(self, tmp_path):
        """真活(退出码 259=STILL_ACTIVE)→ 判活,拒启防孤儿。"""
        self._exit_code = 259
        k = self._mock_kernel32(open_ok=True, get_exit_ok=True)
        with patch("ctypes.windll.kernel32", k):
            from orchestrator.dashboard.app import _pid_alive_default
            assert _pid_alive_default(4242) is True
        pool = tmp_path / "pool"
        _write_lock(pool, pid=4242)
        with patch("ctypes.windll.kernel32", k):
            with pytest.raises(SystemExit) as e:
                acquire_pid_lock(pool)
        assert "4242" in str(e.value)

    def test_get_exit_code_failure_judged_dead(self, tmp_path):
        """GetExitCodeProcess 调用失败(句柄失效/权限)→ 判死,可回收。"""
        k = self._mock_kernel32(open_ok=True, get_exit_ok=False)
        with patch("ctypes.windll.kernel32", k):
            from orchestrator.dashboard.app import _pid_alive_default
            assert _pid_alive_default(5555) is False
