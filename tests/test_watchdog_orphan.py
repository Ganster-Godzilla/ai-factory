"""T-2026-0902-010 S2:孤儿实证——杀父+短墙钟+sleep 复现 009 游荡场景。

链路:假 runner 父进程在 guard 内拉起 sleep 子进程(独立进程组)→ 测试强杀父进程
(复现 009 release 父死孤儿游荡)→ detached helper 父死不灭,到点按组终止 +
watchdog_killed 事件(pid/墙钟/工单/任务字段齐)+ 父死判负落盘(p3 任务标 failed,
按 timeout 判负,恢复走既有 retry/consult 阶梯)。
D5:断言失败一律先打印 `FAIL: <子句>`。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# 裸 `pytest` 不带 cwd 上 sys.path,兜底插仓根(python -m pytest 下幂等)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.daemon import watchdog
from orchestrator.daemon.events import read_events
from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket

REPO_ROOT = Path(__file__).resolve().parents[1]

# 假 runner 父进程:guard 内拉起 sleep 子进程,报 pid 后自己长眠(等测试来杀)
PARENT_CODE = (
    "import subprocess,sys,time;"
    "from orchestrator.daemon import watchdog;"
    "pool,tid=sys.argv[1],sys.argv[2];"
    "g=watchdog.guard(pool,tid,role='dev',task_id='S2',timeout=0.5,grace=0.5);"
    "g.__enter__();"
    "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
    "print('READY',p.pid,flush=True);"
    "time.sleep(300)"
)


@pytest.fixture
def pool(tmp_path):
    p = tmp_path / "pool"
    (p / "tickets").mkdir(parents=True)
    return p


def _check(cond, clause):
    if not cond:
        print(f"FAIL: {clause}")
    assert cond, clause


def _wait_for(pred, timeout=20.0, interval=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(interval)
    return False


def test_orphan_killed_after_parent_death(pool):
    """杀父孤儿实证:父死 + 短墙钟 + sleep → helper 按组终止 + 事件字段齐 + 任务判负。"""
    t = new_ticket(pool, project="p", summary="orphan")
    t.tasks = [{"id": "S2", "title": "x", "status": "doing"}]
    save_ticket(pool, t)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    child_pid = None
    parent = subprocess.Popen(
        [sys.executable, "-c", PARENT_CODE, str(pool), t.id],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = parent.stdout.readline()
        _check(line.startswith("READY "), f"假父进程拉起 sleep 子进程并报 pid(实际输出:{line!r})")
        child_pid = int(line.split()[1])
        _check(watchdog._pid_alive(child_pid), "sleep 子进程活着(游荡场景就绪)")

        parent.kill()  # 杀父:复现 009 release 父死孤儿游荡(TerminateProcess,无清理)
        parent.wait()
        _check(not watchdog._pid_alive(parent.pid), "父进程已死")

        def _killed_events():
            return [e for e in read_events(pool, t.id) if e["event"] == "watchdog_killed"]

        _check(_wait_for(lambda: bool(_killed_events())),
               "父死后 helper 不灭,短墙钟到点写 watchdog_killed 事件")
        e = _killed_events()[0]
        _check(e["pid"] == child_pid, "事件 pid=被杀组根")
        _check(isinstance(e.get("wall_clock_s"), (int, float)) and e["wall_clock_s"] > 0,
               "事件带墙钟字段")
        _check(e["ticket"] == t.id, "事件带工单字段")
        _check(e["task"] == "S2", "事件带任务字段")

        _check(_wait_for(lambda: not watchdog._pid_alive(child_pid), timeout=10),
               "孤儿进程组被按组终止(不再游荡)")

        def _task_failed():
            task = load_ticket(pool, t.id).tasks[0]
            return task.get("status") == "failed"

        _check(_wait_for(_task_failed, timeout=10),
               "父死判负落盘:p3 任务按 timeout 标 failed")
        task = load_ticket(pool, t.id).tasks[0]
        _check("watchdog_killed" in task.get("last_error", ""),
               "last_error 留痕 watchdog_killed(timeout 判负)")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        # 兜底清扫:断言失败时别留游荡 sleep 污染验收工位
        if child_pid is not None and watchdog._pid_alive(child_pid):
            watchdog._kill_tree(child_pid, child_pid)
