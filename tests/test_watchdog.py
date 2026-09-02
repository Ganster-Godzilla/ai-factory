"""T-2026-0902-010 S1:watchdog 父活场景单测。

覆盖:短命令过 guard 正常返回 + 注册表闭环 + helper 退出 + 无事件;
子进程独立进程组归属;孙进程泄漏由 helper 到点按组清扫;
helper 杀组后 guard.killed 标记暴露(供 runner 改写 timeout);
父活探测与父死判负落盘的纯函数单测。
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


@pytest.fixture
def pool(tmp_path):
    p = tmp_path / "pool"
    (p / "tickets").mkdir(parents=True)
    return p


def _check(cond, clause):
    if not cond:
        print(f"FAIL: {clause}")
    assert cond, clause


def _wait_for(pred, timeout=15.0, interval=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(interval)
    return False


TID = "T-2026-0902-010"


def test_guard_normal_return_and_registry_closed(pool):
    """父活+准时收工:adapter 返回 → guard 标 closed → helper 见全 resolved 退出,零事件。"""
    with watchdog.guard(pool, TID, role="pm", timeout=30) as g:
        r = subprocess.run([sys.executable, "-c", "print('hi')"], capture_output=True)
    _check(r.returncode == 0, "guard 内短命令正常返回")
    _check(g.killed is False, "准时收工 guard.killed 为假")
    reg = Path(g.registry_path)
    _check(_wait_for(lambda: not reg.exists(), timeout=15),
           "注册表闭环:全部 closed 后 helper 删除文件并退出")
    _check(_wait_for(lambda: g.helper_exited(), timeout=15), "helper 进程退出,无常驻")
    _check(read_events(pool, TID) == [], "准时收工零事件")


def test_child_in_new_process_group(pool):
    """guard 期间创建的子进程被强制挂独立进程组并登记注册表。"""
    with watchdog.guard(pool, TID, role="dev", timeout=30) as g:
        proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        try:
            entries = watchdog.read_registry(Path(g.registry_path))
            _check(len(entries) == 1, "注册表登记本次子进程")
            _check(entries[0]["pid"] == proc.pid, "登记 pid 正确")
            _check(entries[0]["pgid"] == proc.pid, "子进程为独立进程组组长(pgid==pid)")
            _check(entries[0]["status"] == "pending", "登记初始状态 pending")
            if os.name != "nt":
                _check(os.getpgid(proc.pid) == proc.pid, "posix: getpgid 证实新会话")
        finally:
            proc.kill()
            proc.wait()


def test_grandchild_leak_swept_by_helper(pool, tmp_path):
    """父活+超时残留:guard 退出时子进程仍活着 → pending 留给 helper,
    到点( timeout+grace )按组清扫整棵树(含孙进程)并写 watchdog_killed 事件。"""
    gpid_file = tmp_path / "grandchild.pid"
    child_code = (
        "import subprocess,sys,time,pathlib;"
        "g=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(g.pid));"
        "time.sleep(300)"
    )
    with watchdog.guard(pool, TID, role="dev", task_id="S1",
                        timeout=0.5, grace=0.5):
        proc = subprocess.Popen([sys.executable, "-c", child_code, str(gpid_file)])
        _check(_wait_for(gpid_file.exists, timeout=10), "孙进程已拉起")
        # guard 退出时子进程仍活着:登记项保持 pending,交 helper 到点清扫
    gpid = int(gpid_file.read_text())

    def _killed_events():
        return [e for e in read_events(pool, TID) if e["event"] == "watchdog_killed"]

    _check(_wait_for(lambda: bool(_killed_events()), timeout=20),
           "helper 到点写 watchdog_killed 事件")
    e = _killed_events()[0]
    _check(e["pid"] == proc.pid, "事件 pid=被杀组根")
    _check(e["ticket"] == TID, "事件带 ticket 字段")
    _check(e["role"] == "dev" and e["task"] == "S1", "事件带 role/task 字段")
    _check(isinstance(e.get("wall_clock_s"), (int, float)), "事件带墙钟字段")
    _check(_wait_for(lambda: proc.poll() is not None, timeout=10),
           "子进程组根已终止")
    _check(_wait_for(lambda: not watchdog._pid_alive(gpid), timeout=10),
           "孙进程被按组连带清扫")


def test_guard_killed_flag_exposed_when_helper_kills(pool):
    """helper 杀组发生在 guard 未退出时:guard 退出回查注册表暴露 killed 标记。"""
    with watchdog.guard(pool, TID, role="dev", timeout=0.5, grace=0.3) as g:
        proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(300)"])
        reg = Path(g.registry_path)

        def _marked_killed():
            return reg.exists() and any(
                e["status"] == "killed" for e in watchdog.read_registry(reg))

        _check(_wait_for(_marked_killed, timeout=20), "helper 到点标 killed")
    _check(g.killed is True, "guard 退出暴露 killed 标记(供 runner 改写 timeout)")
    proc.wait()


def test_pid_alive_probe():
    _check(watchdog._pid_alive(os.getpid()), "活进程探测为真")
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    _check(_wait_for(lambda: not watchdog._pid_alive(p.pid), timeout=5),
           "死进程探测为假")


def test_mark_task_failed_writes_ticket(pool):
    """父死判负落盘(纯函数):p3 任务标 failed + last_error 留痕。"""
    t = new_ticket(pool, project="p", summary="x")
    t.tasks = [{"id": "S1", "title": "x", "status": "doing"}]
    save_ticket(pool, t)
    watchdog._mark_task_failed(pool, t.id, "S1", 3.2)
    r = load_ticket(pool, t.id)
    _check(r.tasks[0]["status"] == "failed", "父死场景 p3 任务标 failed")
    err = r.tasks[0].get("last_error", "")
    _check("watchdog_killed" in err and "父死" in err, "last_error 留痕 watchdog_killed(父死)")
