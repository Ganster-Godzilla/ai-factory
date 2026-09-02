"""T-2026-0902-010:runner 进程组墙钟看门狗(适配器无关)。

角色超时帽只在父进程活着时生效,父死孤儿无限烧(009 release 游荡 2h 实证)。
本模块在 runner 进程内对 `subprocess.Popen.__init__` 做 guard 生命周期内的局部补丁:
guard 期间创建的每个子进程被强制挂独立进程组并登记注册表;首个登记惰性拉起
**detached helper 进程**(父死不灭),按注册表 0.5s 轮询,到点按组终止整棵进程树、
写 `watchdog_killed` 事件;若父已死且对应 p3 任务,helper 直标任务 failed(没人替它
判负,恢复时走既有 retry/consult 阶梯)。

注册表:`pool/watchdog/<ticket>-<task|role>-<epoch_ms>.jsonl`(每 guard 一文件,
行一条 JSON):{pid, pgid, deadline, created, ticket, task, role, status},
status ∈ pending / closed / killed。

helper 退出与注册表清理规则:
- 全部 resolved 且无 killed(父正常收工)→ 删文件退出;
- 全部 resolved 且有 killed 且父活 → 留文件退出(等 guard 退出回查 killed 标记,
  由 guard 收尾删除);父死 → 删文件退出;
- 硬上限 max(deadline)+120s 自毁,无常驻守护。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from orchestrator.daemon.events import append_event

GRACE = 15.0           # 让位间隔:父活时 subprocess.run(timeout=) 先触发,看门狗不抢跑
POLL_INTERVAL = 0.5
HARD_CAP_SLACK = 120.0

_IS_NT = os.name == "nt"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 注册表 IO

def read_registry(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_registry(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8", newline="\n",
    )


# ---------------------------------------------------------------- 平台原语

def _pid_alive(pid: int) -> bool:
    """父活探测 / 进程存在探测。nt:OpenProcess+退出码;posix:kill(pid, 0)。"""
    if _IS_NT:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_tree(pid: int, pgid: int) -> None:
    """按组终止整棵进程树。P0 单级强杀;W5 分级终止留后续工单。"""
    if _IS_NT:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    else:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _mark_task_failed(pool: Path, ticket_id: str, task_id: str, wall: float) -> None:
    """父死判负落盘:helper 探父已死时,把 p3 任务直标 failed(timeout 判负留痕),
    恢复时走既有 retry/consult 阶梯。父活由 runner 侧判负,helper 不动工单
    (避免与 runner 的 save_ticket 写竞态)。"""
    from orchestrator.daemon.ticket import load_ticket, save_ticket
    try:
        t = load_ticket(pool, ticket_id)
    except Exception:
        return  # 工单不存在/不可读:事件流已留痕,不阻塞 helper 主职
    changed = False
    for task in t.tasks:
        if isinstance(task, dict) and task.get("id") == task_id:
            task["status"] = "failed"
            task["last_error"] = f"watchdog_killed: 墙钟 {wall:g}s 到点(父死)"
            changed = True
    if changed:
        save_ticket(pool, t)


# ---------------------------------------------------------------- guard

class guard:
    """runner 进程内上下文管理器:包裹一次 adapter.run(packet)。

    进入:deadline = now + timeout + grace;patch subprocess.Popen.__init__。
    期间每个子进程:强制独立进程组(nt CREATE_NEW_PROCESS_GROUP 按位或入,
    尊重调用方其余 flag;posix 仅在调用方未显式设置时 start_new_session=True),
    随后登记注册表;首个登记惰性拉起 detached helper。
    退出:还原 Popen;已退出的登记项标 closed,仍活着的留 pending 交 helper
    到点清扫;回查注册表,有 killed 项则暴露 self.killed(供 runner 改写
    timeout 判负,语义与适配器自报一致)。
    """

    def __init__(self, pool, ticket, role: str | None = None,
                 task_id: str | None = None, timeout: float = 300,
                 grace: float = GRACE):
        self.pool = Path(pool)
        self.ticket_id = getattr(ticket, "id", ticket)
        self.role = role
        self.task_id = task_id
        self.timeout = timeout
        self.grace = grace
        self.killed = False
        self.registry_path: Path | None = None
        self._orig_init = None
        self._patched = None
        self._procs: list[subprocess.Popen] = []
        self._helper: subprocess.Popen | None = None
        self._deadline = 0.0

    def helper_exited(self) -> bool:
        return self._helper is not None and self._helper.poll() is not None

    # -- 进入/退出 --

    def __enter__(self) -> "guard":
        self._deadline = time.time() + self.timeout + self.grace
        self._orig_init = subprocess.Popen.__init__

        def patched(popen_self, *args, **kwargs):
            if _IS_NT:
                cf = kwargs.get("creationflags") or 0
                kwargs["creationflags"] = cf | subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs.setdefault("start_new_session", True)
            self._orig_init(popen_self, *args, **kwargs)
            self._register(popen_self)

        self._patched = patched
        subprocess.Popen.__init__ = patched
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        subprocess.Popen.__init__ = self._orig_init
        if self.registry_path is None:
            return False
        dead = {p.pid for p in self._procs if p.poll() is not None}
        entries = read_registry(self.registry_path)
        self.killed = any(e["status"] == "killed" for e in entries)
        if entries:
            for e in entries:
                if e["status"] == "pending" and e["pid"] in dead:
                    e["status"] = "closed"
            try:
                _write_registry(self.registry_path, entries)
            except FileNotFoundError:
                pass
        # 收尾:killed&父活场景 helper 留文件先走;helper 已退出且全部有终态则删
        if self.helper_exited():
            self._helper.wait()  # 显式 reap,防 GC 时 __del__ 轮询已关句柄告警
            if self.registry_path.exists():
                rest = read_registry(self.registry_path)
                if rest and all(e["status"] != "pending" for e in rest):
                    self.registry_path.unlink(missing_ok=True)
        return False

    # -- 登记与 helper 拉起 --

    def _register(self, proc: subprocess.Popen) -> None:
        if self.registry_path is None:
            wd = self.pool / "watchdog"
            wd.mkdir(parents=True, exist_ok=True)
            tag = self.task_id or self.role or "role"
            epoch_ms = time.time_ns() // 1_000_000
            self.registry_path = wd / f"{self.ticket_id}-{tag}-{epoch_ms}.jsonl"
        entry = {
            "pid": proc.pid,
            "pgid": proc.pid,  # 新进程组/会话组长:posix pgid==pid;nt taskkill 以 pid 为树根
            "deadline": self._deadline,
            "created": time.time(),
            "ticket": self.ticket_id,
            "task": self.task_id,
            "role": self.role,
            "status": "pending",
        }
        with self.registry_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._procs.append(proc)
        if self._helper is None:
            self._spawn_helper()

    def _spawn_helper(self) -> None:
        """惰性拉起 detached helper:不继承句柄、不写 stdout,父死存活。
        nt 加 CREATE_BREAKAWAY_FROM_JOB 防 runner 被 Job Object 罩住时连坐。"""
        argv = [sys.executable, "-m", "orchestrator.daemon.watchdog",
                str(self.registry_path), "--parent-pid", str(os.getpid())]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_repo_root()) + os.pathsep + env.get("PYTHONPATH", "")
        kwargs = dict(cwd=str(_repo_root()), env=env,
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, close_fds=True)
        if _IS_NT:
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
            )
        else:
            kwargs["start_new_session"] = True
        # helper 自身不得进注册表(否则到点被杀):临时还原补丁再拉起
        subprocess.Popen.__init__ = self._orig_init
        try:
            self._helper = subprocess.Popen(argv, **kwargs)
        finally:
            subprocess.Popen.__init__ = self._patched


# ---------------------------------------------------------------- helper

def _helper_main(registry: Path, parent_pid: int) -> int:
    """detached 看门狗:轮询注册表,到点按组终止+事件+父死判负落盘;
    全部 resolved 即退出;硬上限 max(deadline)+120s 自毁。"""
    pool = registry.parent.parent
    entries = read_registry(registry)
    hard_cap = (max((e["deadline"] for e in entries), default=time.time())
                + HARD_CAP_SLACK)
    while True:
        entries = read_registry(registry)
        if not entries:
            return 0  # 文件已被 guard 收走或为空
        now = time.time()
        changed = False
        for e in entries:
            if e["status"] != "pending" or now < e["deadline"]:
                continue
            if not _pid_alive(e["pid"]):
                e["status"] = "closed"  # 到点前已自然退出,无需动刀
                changed = True
                continue
            wall = round(now - e.get("created", now), 1)
            _kill_tree(e["pid"], e.get("pgid", e["pid"]))
            e["status"] = "killed"
            changed = True
            append_event(pool, e["ticket"], "system", "watchdog_killed",
                         pid=e["pid"], wall_clock_s=wall,
                         task=e.get("task"), role=e.get("role"))
            if not _pid_alive(parent_pid) and e.get("task"):
                # 父死:没人替它判负,helper 直标 p3 任务 failed
                _mark_task_failed(pool, e["ticket"], e["task"], wall)
        if changed:
            _write_registry(registry, entries)
        if all(e["status"] != "pending" for e in entries):
            has_killed = any(e["status"] == "killed" for e in entries)
            # killed&父活:留文件等 guard 退出回查(guard 收尾删除);其余即删
            if not has_killed or not _pid_alive(parent_pid):
                registry.unlink(missing_ok=True)
            return 0
        if now > hard_cap:
            return 0  # 自毁,无常驻守护
        time.sleep(POLL_INTERVAL)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orchestrator.daemon.watchdog")
    ap.add_argument("registry", type=Path)
    ap.add_argument("--parent-pid", type=int, required=True)
    args = ap.parse_args(argv)
    return _helper_main(args.registry, args.parent_pid)


if __name__ == "__main__":
    raise SystemExit(main())
