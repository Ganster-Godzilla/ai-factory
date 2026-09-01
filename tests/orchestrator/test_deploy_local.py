"""G5:local 流水线(T-2026-0901-004 F7 + design §5)。

流水线:按 processes 清单逐个 pidfile 重启(读 pid → terminate → spawn start_cmd
并回写 pid)→ 本地冒烟 → 发布记录章节写入。治"合并后忘重启"病根。

覆盖(design §5 / 测试用例设计映射):
- F7 local 进程重启:pidfile 读/写/路径解析、pid 存活判定(真实进程)、
  真实 spawn→terminate 闭环、restart_local_process 单条重启留痕
  (存活 terminate / 陈旧 pid 跳过 / 首启无 pidfile 三分支)
- 多进程清单按序重启 + 重启留痕进部署清单
- 本地冒烟:全绿写发布记录(部署清单/冒烟结果/回滚方案);非全绿判负
- 失败路径不静默:冒烟失败 / spawn 失败 / git describe 失败 → incident 单 +
  回链 + 非零退出 + 回滚说明可照抄
- CLI __main__:local 形态走真实流水线,0=全绿,失败非零退出
"""
import os
import sys
from pathlib import Path

import pytest

from orchestrator.daemon import deploy
from orchestrator.daemon.deploy import (
    EXIT_DEPLOY_FAILED, SECTION_DEPLOY, SECTION_FAILURE, SECTION_ROLLBACK,
    SECTION_SMOKE, SmokeResult, release_record_path, run_deploy,
)
from orchestrator.daemon.ticket import load_ticket, new_ticket

LOCAL_SMOKE_URLS = ["http://127.0.0.1:8765/"]
PROC = {"name": "dashboard", "pidfile": ".orc-local/dashboard.pid",
        "start_cmd": "python -m orchestrator.daemon.cli dashboard --port 8765"}


def _cfg(pd, **over) -> dict:
    """local 形态登记配置(与 orchestrator.yaml 同构;over 可覆盖/删除键)。"""
    conf = {"target": "local",
            "processes": [dict(PROC)],
            "smoke": list(LOCAL_SMOKE_URLS)}
    conf.update(over)
    return {"deploy": {"ai-factory": conf},
            "projects": {"ai-factory": str(pd)}}


def _project(tmp_path) -> Path:
    """本地项目 checkout 快照(document/business 由 _ticket 建工单文件夹)。"""
    pd = tmp_path / "proj"
    (pd / "document" / "business").mkdir(parents=True)
    return pd


def _ticket(pool, pd, project="ai-factory"):
    """建真实工单 + 建对应工单文件夹(发布记录落点,design §4)。"""
    t = new_ticket(pool, project=project, summary="G5 local 流水线测试",
                   created_by="test")
    tid_dir = pd / "document" / "business" / f"{t.id}-local测试"
    (tid_dir / "05_部署交付").mkdir(parents=True)
    return t


def _only_incident(pool, orig_id):
    ids = [p.stem for p in (pool / "tickets").glob("T-*.yaml") if p.stem != orig_id]
    assert len(ids) == 1, f"期望 1 个 incident 单,实际 {ids}"
    return load_ticket(pool, ids[0])


def _green_smoke():
    return [SmokeResult(url=LOCAL_SMOKE_URLS[0], status=200, elapsed_ms=1, ok=True)]


class FakeProcs:
    """G5 F7 fake:记录 pidfile/进程操作序列,不真杀真起。

    - read_pid:pidfile 读出的旧 pid(None=首启无 pidfile)
    - alive:存活判定注入(False=陈旧 pid)
    - new_pid:spawn 返回的新 pid
    - spawn_error:spawn 抛错注入(失败路径)
    - git_version:_local_run 对 git describe 的应答(""=版本判定失败)
    - calls:[(kind, *args), ...] 记录 read/terminate/spawn/write 序列
    """

    def __init__(self, monkeypatch):
        self.calls: list[tuple] = []
        self.read_pid = 1234
        self.alive = True
        self.new_pid = 9999
        self.spawn_error: Exception | None = None
        self.git_version = "v1.2.3"
        monkeypatch.setattr(deploy, "_read_pid", self._read_pid)
        monkeypatch.setattr(deploy, "_pid_alive", lambda pid: self.alive)
        monkeypatch.setattr(deploy, "_terminate_pid", self._terminate_pid)
        monkeypatch.setattr(deploy, "_spawn_process", self._spawn_process)
        monkeypatch.setattr(deploy, "_write_pid", self._write_pid)
        monkeypatch.setattr(
            deploy, "_local_run",
            lambda cmd, cwd=None: self.git_version if "describe" in cmd else "")

    def _read_pid(self, pidfile):
        self.calls.append(("read", str(pidfile)))
        return self.read_pid

    def _terminate_pid(self, pid):
        self.calls.append(("terminate", pid))

    def _spawn_process(self, start_cmd, cwd=None, log_path=None):
        self.calls.append(("spawn", start_cmd, str(cwd), str(log_path)))
        if self.spawn_error is not None:
            raise self.spawn_error
        return self.new_pid

    def _write_pid(self, pidfile, pid):
        self.calls.append(("write", str(pidfile), pid))


@pytest.fixture
def fake_smoke(monkeypatch):
    """monkeypatch deploy.smoke:记录被调 URL 清单并返回注入结果(单测不发真实 HTTP)。"""
    calls: list[list[str]] = []

    def install(results: list[SmokeResult]) -> list[list[str]]:
        def _smoke(urls, *a, **k):
            calls.append(list(urls))
            return results

        monkeypatch.setattr(deploy, "smoke", _smoke)
        return calls

    return install


# --- pidfile 读写与路径解析 ------------------------------------------------------


def test_local_pidfile_path_resolution(tmp_path):
    assert deploy._local_pidfile_path(tmp_path, ".orc-local/dashboard.pid") \
        == tmp_path / ".orc-local" / "dashboard.pid"   # 相对路径按 checkout 解析
    abs_p = tmp_path / "abs" / "x.pid"
    assert deploy._local_pidfile_path(tmp_path, str(abs_p)) == abs_p  # 绝对路径原样


def test_pidfile_read_write_roundtrip(tmp_path):
    pf = tmp_path / ".orc-local" / "x.pid"
    assert deploy._read_pid(pf) is None            # 缺失 → None
    deploy._write_pid(pf, 4242)
    assert pf.read_text(encoding="utf-8").strip() == "4242"
    assert deploy._read_pid(pf) == 4242
    pf.write_text("not-a-pid\n", encoding="utf-8")
    assert deploy._read_pid(pf) is None            # 内容非数字 → 陈旧
    pf.write_text("", encoding="utf-8")
    assert deploy._read_pid(pf) is None            # 空文件 → 陈旧


# --- pid 存活判定(真实进程,design §5) --------------------------------------------


def test_pid_alive_current_true_and_impossible_false():
    assert deploy._pid_alive(os.getpid()) is True
    assert deploy._pid_alive(2 ** 30) is False     # 远超系统上限的 pid:不存在


def test_real_spawn_terminate_roundtrip(tmp_path):
    """真实进程闭环:_spawn_process 起长驻进程(输出落 log 文件,不走管道)→
    存活判定 True → _terminate_pid 后不再存活,pidfile 重启语义成立。"""
    pd = tmp_path / "proj"
    pd.mkdir()
    log = pd / ".orc-local" / "t.log"
    pid = deploy._spawn_process(f'"{sys.executable}" -c "import time; time.sleep(30)"',
                                cwd=pd, log_path=log)
    try:
        assert deploy._pid_alive(pid) is True
        assert log.is_file()                       # 长驻输出已落盘
        deploy._terminate_pid(pid)
        assert deploy._pid_alive(pid) is False
    finally:
        try:
            deploy._terminate_pid(pid)             # 兜底清理:断言失败也不留进程
        except Exception:
            pass


# --- restart_local_process 单条重启留痕(F7) ---------------------------------------


def test_restart_local_process_alive_pid_terminates_then_spawns(tmp_path, monkeypatch):
    pd = tmp_path / "proj"
    pd.mkdir()
    procs = FakeProcs(monkeypatch)

    out = deploy.restart_local_process(pd, PROC)

    assert out == {"name": "dashboard", "old_pid": 1234, "pid": 9999}
    assert procs.calls == [
        ("read", str(pd / ".orc-local" / "dashboard.pid")),
        ("terminate", 1234),
        ("spawn", PROC["start_cmd"], str(pd),
         str(pd / ".orc-local" / "dashboard.log")),
        ("write", str(pd / ".orc-local" / "dashboard.pid"), 9999),
    ]


def test_restart_local_process_stale_pid_skips_terminate(tmp_path, monkeypatch):
    pd = tmp_path / "proj"
    pd.mkdir()
    procs = FakeProcs(monkeypatch)
    procs.alive = False                            # pidfile 里是陈旧 pid

    deploy.restart_local_process(pd, PROC)

    assert [c[0] for c in procs.calls] == ["read", "spawn", "write"]  # 无 terminate
    assert not any(c[0] == "terminate" for c in procs.calls)


def test_restart_local_process_first_start_no_pidfile(tmp_path, monkeypatch):
    pd = tmp_path / "proj"
    pd.mkdir()
    procs = FakeProcs(monkeypatch)
    procs.read_pid = None                          # 首启:无旧 pid

    out = deploy.restart_local_process(pd, PROC)

    assert out["old_pid"] is None and out["pid"] == 9999
    assert [c[0] for c in procs.calls] == ["read", "spawn", "write"]


# --- F7:local 全绿流水线(design §5) ----------------------------------------------


def test_local_full_green_restart_sequence_and_record(pool, tmp_path, monkeypatch,
                                                      fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    procs = FakeProcs(monkeypatch)
    smoke_calls = fake_smoke(_green_smoke())

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == 0
    # 重启序列:读 pid → 存活 → terminate → spawn → 回写新 pid
    assert [c[0] for c in procs.calls] == ["read", "terminate", "spawn", "write"]
    assert procs.calls[1][1] == 1234                       # terminate 旧 pid
    assert procs.calls[2][1] == PROC["start_cmd"]          # spawn start_cmd
    assert procs.calls[2][2] == str(pd)                    # cwd=项目 checkout
    assert procs.calls[2][3] == str(pd / ".orc-local" / "dashboard.log")
    assert procs.calls[3][1] == str(pd / ".orc-local" / "dashboard.pid")
    assert procs.calls[3][2] == 9999                       # 回写新 pid
    # 冒烟按配置清单执行
    assert smoke_calls == [list(LOCAL_SMOKE_URLS)]
    # 发布记录:部署清单(版本/目标/重启进程)+ 冒烟结果 + 回滚方案
    record = release_record_path(pd, t.id)
    assert record is not None and record.is_file()
    text = record.read_text(encoding="utf-8")
    assert f"## {SECTION_DEPLOY}" in text
    assert "`v1.2.3`" in text and "`local`" in text
    assert "重启进程" in text and "dashboard" in text and "9999" in text
    assert "1234" in text                                    # 旧 pid 留痕
    assert f"## {SECTION_SMOKE}" in text and "全绿,发布成功" in text
    assert f"## {SECTION_ROLLBACK}" in text
    assert "git checkout" in text and PROC["start_cmd"] in text  # 回滚可照抄


def test_local_multiple_processes_restarted_in_order(pool, tmp_path, monkeypatch,
                                                     fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    procs = FakeProcs(monkeypatch)
    fake_smoke(_green_smoke())
    cfg = _cfg(pd)
    cfg["deploy"]["ai-factory"]["processes"] = [
        {"name": "dashboard", "pidfile": ".orc-local/dashboard.pid",
         "start_cmd": "python -m orchestrator.daemon.cli dashboard --port 8765"},
        {"name": "worker", "pidfile": ".orc-local/worker.pid",
         "start_cmd": "python -m orchestrator.daemon.worker"},
    ]

    code = run_deploy(pool, cfg, t, pd)

    assert code == 0
    spawns = [c for c in procs.calls if c[0] == "spawn"]
    assert [s[1] for s in spawns] == [
        "python -m orchestrator.daemon.cli dashboard --port 8765",
        "python -m orchestrator.daemon.worker",
    ]
    assert [s[3] for s in spawns] == [
        str(pd / ".orc-local" / "dashboard.log"),
        str(pd / ".orc-local" / "worker.log"),
    ]
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert "dashboard" in text and "worker" in text         # 两条重启留痕都进清单


def test_deploy_manifest_processes_note_rendered():
    text = deploy.render_deploy_manifest(
        version="v1", target="local", when="t",
        processes_note="dashboard(旧 pid 1234 → 新 pid 9999)")
    assert f"## {SECTION_DEPLOY}" in text
    assert "重启进程" in text and "dashboard" in text
    assert "1234" in text and "9999" in text


# --- 失败路径:冒烟失败 / spawn 失败 / 版本失败(F5,不静默) -------------------------


def test_local_smoke_failure_incident_and_rollback(pool, tmp_path, monkeypatch,
                                                   fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    procs = FakeProcs(monkeypatch)
    fake_smoke([SmokeResult(url=LOCAL_SMOKE_URLS[0], status=404, elapsed_ms=9,
                            ok=False)])

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    # 重启已发生(先重启后冒烟),冒烟失败不写成功记录
    assert [c[0] for c in procs.calls] == ["read", "terminate", "spawn", "write"]
    inc = _only_incident(pool, t.id)
    assert inc.type == "incident" and inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert f"## {SECTION_FAILURE}" in text and inc.id in text
    assert f"## {SECTION_SMOKE}" in text and "404" in text and "FAIL" in text
    assert f"## {SECTION_ROLLBACK}" in text
    assert "git checkout <上一 tag>" in text               # local 回滚占位可照抄
    assert PROC["start_cmd"] in text                       # 逐条重启命令可照抄


def test_local_spawn_failure_creates_incident(pool, tmp_path, monkeypatch):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    procs = FakeProcs(monkeypatch)
    procs.spawn_error = RuntimeError(
        "本地命令失败(exit=1): python -m orchestrator.daemon.cli dashboard")

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    inc = _only_incident(pool, t.id)
    assert inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert f"## {SECTION_FAILURE}" in text and "本地命令失败" in text


def test_local_git_describe_failure_creates_incident(pool, tmp_path, monkeypatch,
                                                     fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    procs = FakeProcs(monkeypatch)
    procs.git_version = ""            # git describe 无输出 → 版本判定异常
    fake_smoke(_green_smoke())

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    assert not any(c[0] == "spawn" for c in procs.calls)  # 未触碰进程
    inc = _only_incident(pool, t.id)
    assert inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert "git describe 无输出" in text


# --- CLI __main__(design §接口契约) ----------------------------------------------


def test_cli_main_local_pipeline_green(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    procs = FakeProcs(monkeypatch)
    fake_smoke(_green_smoke())
    cfg = _cfg(pd)
    cfg["pool"] = str(pool)
    monkeypatch.setattr(deploy, "_load_cfg", lambda: cfg)

    code = deploy.main([t.id])

    assert code == 0
    assert release_record_path(pd, t.id).is_file()
    assert any(c[0] == "spawn" for c in procs.calls)


def test_cli_main_local_smoke_failure_returns_1(pool, tmp_path, monkeypatch,
                                                fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    FakeProcs(monkeypatch)
    fake_smoke([SmokeResult(url=LOCAL_SMOKE_URLS[0], status=500, elapsed_ms=5,
                            ok=False)])
    cfg = _cfg(pd)
    cfg["pool"] = str(pool)
    monkeypatch.setattr(deploy, "_load_cfg", lambda: cfg)

    assert deploy.main([t.id]) == 1        # 非零退出:release 角色判负,不静默
    assert _only_incident(pool, t.id).related_ticket == t.id
