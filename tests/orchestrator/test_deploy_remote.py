"""G4:remote 流水线(T-2026-0901-004 F2 + design §2 / §接口契约)。

流水线:本地构建→tar+ssh 上传→解包留版 chown 归一→依赖/.env 前置→current 回切→
restart_cmd→冒烟→发布记录章节写入;CLI __main__。

覆盖(design §2 / 测试用例设计映射):
- F2 remote 脚本化:fake runner 断言命令序列(含 chown 归一/解包留版/回切/重启)
- 依赖差异前置:不一致中止 FAIL(无回切/重启/冒烟),--allow-deps-change 放行
  且发布记录必写 venv 重建说明;首装无基准保守判差异
- .env 差异仅 key 名:差异清单进部署单,值不出现在任何命令/记录(F6/R9)
- 构建产物缺失 / ssh 命令失败:自动建 incident 不静默
- 冒烟失败:incident + 冒烟留痕 + 回滚说明 + 非零退出
- 未登记 deploy:显式声明"未登记 deploy,本单纯代码交付"
- CLI __main__:tid 解析 / --allow-deps-change 透传 / 未知工单与未登记项目报错退出
"""
from pathlib import Path

import pytest

from orchestrator.daemon import deploy
from orchestrator.daemon.deploy import (
    DEPS_CHANGE_NOTE, EXIT_DEPLOY_FAILED, SECTION_DEPLOY, SECTION_FAILURE,
    SECTION_ROLLBACK, SECTION_SMOKE, UNREGISTERED_DEPLOY_NOTE, SmokeResult,
    release_record_path, requirements_sha, run_deploy,
)
from orchestrator.daemon.ticket import load_ticket, new_ticket

APP = "/opt/sk-video-studio"
KEY = "~/.ssh/sk-aliyun-47"
HOST = "deploy@47.109.84.154"
RESTART = "sudo -n systemctl restart sk-api"
SMOKE_URLS = ["http://47.109.84.154/api/health", "http://47.109.84.154/"]


def _cfg(pd, **over) -> dict:
    """remote 形态登记配置(与 orchestrator.yaml 同构;over 可覆盖/删除键)。"""
    conf = {
        "target": "remote",
        "host": HOST,
        "ssh_key": KEY,
        "app_dir": APP,
        "service": "sk-api",
        "build_cmd": "npm run build --prefix apps/web",
        "dist_dir": "apps/web/dist",
        "requirements": "apps/api/requirements.txt",
        "env_example": ".env.example",
        "remote_env": f"{APP}/.env",
        "restart_cmd": RESTART,
        "smoke": list(SMOKE_URLS),
    }
    conf.update(over)
    return {"deploy": {"sk-video-studio": conf},
            "projects": {"sk-video-studio": str(pd)}}


def _project(tmp_path) -> Path:
    """本地项目 checkout 快照:requirements/env_example/dist 全齐(G1 路径校验通过)。"""
    pd = tmp_path / "proj"
    (pd / "apps" / "api").mkdir(parents=True)
    (pd / "apps" / "api" / "requirements.txt").write_text("flask==3.0\n", encoding="utf-8")
    (pd / "apps" / "web" / "dist").mkdir(parents=True)
    (pd / "apps" / "web" / "dist" / "index.html").write_text("<html/>", encoding="utf-8")
    (pd / ".env.example").write_text("API_KEY=super-secret-value\nDB_PASS=another-secret\n",
                                     encoding="utf-8")
    return pd


def _ticket(pool, project_dir, project="sk-video-studio"):
    """建真实工单 + 建对应工单文件夹(发布记录落点,design §4)。"""
    t = new_ticket(pool, project=project, summary="G4 remote 流水线测试", created_by="test")
    tid_dir = project_dir / "document" / "business" / f"{t.id}-remote测试"
    (tid_dir / "05_部署交付").mkdir(parents=True)
    return t


def _only_incident(pool, orig_id):
    ids = [p.stem for p in (pool / "tickets").glob("T-*.yaml") if p.stem != orig_id]
    assert len(ids) == 1, f"期望 1 个 incident 单,实际 {ids}"
    return load_ticket(pool, ids[0])


def _green_smoke():
    return [SmokeResult(url=u, status=200, elapsed_ms=1, ok=True) for u in SMOKE_URLS]


class FakeRunner:
    """G4 F2 fake runner:记录 local/ssh 命令序列并按片段回放输出,不真跑。

    - local: [(cmd, cwd), ...];ssh: [(key, host, remote_cmd), ...]
    - answer(fragment, output):remote/local 命令含 fragment 时返回 output(回放)
    """

    def __init__(self, monkeypatch):
        self.local: list[tuple[str, str | None]] = []
        self.ssh: list[tuple[str, str, str]] = []
        self.answers: dict[str, str] = {}
        monkeypatch.setattr(deploy, "_local_run", self._local_run)
        monkeypatch.setattr(deploy, "_ssh_run", self._ssh_run)

    def answer(self, fragment: str, output: str) -> "FakeRunner":
        self.answers[fragment] = output
        return self

    def _local_run(self, cmd, cwd=None):
        self.local.append((cmd, str(cwd) if cwd is not None else None))
        for frag, out in self.answers.items():
            if frag in cmd:
                return out
        return ""

    def _ssh_run(self, key, host, remote_cmd):
        self.ssh.append((key, host, remote_cmd))
        for frag, out in self.answers.items():
            if frag in remote_cmd:
                return out
        return ""


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


def _bundle(pd: Path, ver: str) -> Path:
    # 打包落项目根(相对包名,防盘符冒号被 GNU tar 当远程主机歧义,007 实证)
    return pd / ".orc-local" / f"orc-deploy-sk-video-studio-{ver}.tar.gz"


def _unpack_cmd(ver: str) -> str:
    return (f"mkdir -p {APP}/releases/{ver} && "
            f"tar -xzf {APP}/releases/{ver}.tar.gz -C {APP}/releases/{ver} && "
            f"rm -f {APP}/releases/{ver}.tar.gz && "
            f'chown -R "$(id -u):$(id -g)" {APP}/releases/{ver}')


# --- F2:remote 全绿命令序列(design §2) ------------------------------------------


def test_remote_full_green_sequence_and_record(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    ver, prev = "v1.2.3", "v1.1.0"
    sha = requirements_sha(pd / "apps/api/requirements.txt")
    runner.answer("git describe", ver)
    runner.answer(".requirements.sha", sha)          # 依赖与 current 基准一致
    runner.answer("cut -d= -f1", "API_KEY\nDB_PASS\nNEW_TOKEN")  # 远端 .env 只回 key 名
    runner.answer("readlink", f"releases/{prev}")
    smoke_calls = fake_smoke(_green_smoke())

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == 0
    # 本地命令序列:git describe → 构建 → tar 打包(相对包名,防盘符冒歧义)→ scp 上传
    bundle = _bundle(pd, ver)
    assert [c for c, _ in runner.local] == [
        "git describe --tags --always",
        "npm run build --prefix apps/web",
        f"tar -czf .orc-local/orc-deploy-sk-video-studio-{ver}.tar.gz --exclude=.git --exclude=./.orc-worktrees --exclude=.venv --exclude=node_modules --exclude=__pycache__ --exclude=./data --exclude=./.runtime --exclude=./.env --exclude=./.orc-local --exclude=*.tar.gz .",
        f"scp -i {KEY} {bundle} {HOST}:{APP}/releases/{ver}.tar.gz",
    ]
    assert runner.local[0][1] == str(pd)  # git describe 在项目 checkout 下执行
    assert runner.local[1][1] == str(pd)  # 构建在项目 checkout 下执行
    assert runner.local[2][1] == str(pd)  # tar 在项目根打包(相对包名)
    # 远端命令序列:mkdir → 解包留版+chown 归一 → 依赖前置 → sha 落档 →
    # .env key 名 → readlink → 回切+重启
    assert [c for _, _, c in runner.ssh] == [
        f"mkdir -p {APP}/releases",
        _unpack_cmd(ver),
        (f"test -f {APP}/current/.requirements.sha "
         f"&& cat {APP}/current/.requirements.sha || echo ''"),
        f"echo {sha} > {APP}/releases/{ver}/.requirements.sha",
        f"test -f {APP}/.env && cut -d= -f1 {APP}/.env || echo ''",
        f"test -L {APP}/current && readlink {APP}/current || echo ''",
        f"ln -sfn releases/{ver} {APP}/current && {RESTART}",
    ]
    assert all(k == KEY and h == HOST for k, h, _ in runner.ssh)
    # 冒烟按配置清单执行
    assert smoke_calls == [list(SMOKE_URLS)]
    # 发布记录:部署清单(版本/目标/时间/依赖与 .env 差异)+ 冒烟结果 + 回滚方案
    record = release_record_path(pd, t.id)
    assert record is not None and record.is_file()
    text = record.read_text(encoding="utf-8")
    assert f"## {SECTION_DEPLOY}" in text
    assert f"`{ver}`" in text and "`remote`" in text
    assert "无差异" in text                      # 依赖与基准一致
    assert "NEW_TOKEN" in text                   # .env 差异仅 key 名进部署单
    assert "super-secret-value" not in text      # 值永不落库(R9/F6)
    assert f"## {SECTION_SMOKE}" in text and "PASS" in text
    assert "全绿,发布成功" in text
    assert f"## {SECTION_ROLLBACK}" in text
    assert f"ln -sfn releases/{prev} current" in text  # 上一版回切可照抄
    assert RESTART in text


def test_remote_without_build_cmd_skips_build(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    ver = "abc1234"
    runner.answer("git describe", ver)
    runner.answer(".requirements.sha", requirements_sha(pd / "apps/api/requirements.txt"))
    runner.answer("readlink", "releases/v1.0.0")
    fake_smoke(_green_smoke())
    cfg = _cfg(pd)
    del cfg["deploy"]["sk-video-studio"]["build_cmd"]
    del cfg["deploy"]["sk-video-studio"]["dist_dir"]

    code = run_deploy(pool, cfg, t, pd)

    assert code == 0
    bundle = _bundle(pd, ver)
    assert [c for c, _ in runner.local] == [
        "git describe --tags --always",
        f"tar -czf .orc-local/orc-deploy-sk-video-studio-{ver}.tar.gz --exclude=.git --exclude=./.orc-worktrees --exclude=.venv --exclude=node_modules --exclude=__pycache__ --exclude=./data --exclude=./.runtime --exclude=./.env --exclude=./.orc-local --exclude=*.tar.gz .",
        f"scp -i {KEY} {bundle} {HOST}:{APP}/releases/{ver}.tar.gz",
    ]


# --- 依赖差异前置(design §2.3) ---------------------------------------------------


def test_remote_deps_mismatch_aborts_before_switch(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    ver = "v1.2.3"
    runner.answer("git describe", ver)
    runner.answer(".requirements.sha", "deadbeef" * 8)  # 与本地不一致
    smoke_calls = fake_smoke(_green_smoke())

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    # 命令序列止于依赖前置检查:无 sha 落档/.env/readlink/回切/重启/冒烟
    assert [c for _, _, c in runner.ssh] == [
        f"mkdir -p {APP}/releases",
        _unpack_cmd(ver),
        (f"test -f {APP}/current/.requirements.sha "
         f"&& cat {APP}/current/.requirements.sha || echo ''"),
    ]
    assert not any("ln -sfn" in c for _, _, c in runner.ssh)
    assert not any("cut -d= -f1" in c for _, _, c in runner.ssh)
    assert smoke_calls == []  # 未到冒烟
    # incident 自动建成 + 回链 + 发布记录失败详情与回滚说明
    inc = _only_incident(pool, t.id)
    assert inc.type == "incident" and inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert f"## {SECTION_FAILURE}" in text and inc.id in text
    assert "依赖差异中止" in text
    assert "--allow-deps-change" in text
    assert f"## {SECTION_ROLLBACK}" in text


def test_remote_deps_mismatch_allowed_continues_with_venv_note(pool, tmp_path, monkeypatch,
                                                               fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    ver = "v1.2.3"
    runner.answer("git describe", ver)
    runner.answer(".requirements.sha", "deadbeef" * 8)  # 不一致但显式放行
    runner.answer("readlink", "releases/v1.1.0")
    fake_smoke(_green_smoke())

    code = run_deploy(pool, _cfg(pd), t, pd, allow_deps_change=True)

    assert code == 0
    assert any(f"ln -sfn releases/{ver}" in c for _, _, c in runner.ssh)  # 继续回切重启
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert DEPS_CHANGE_NOTE in text  # 发布记录必写 venv 重建说明
    assert "venv" in text


def test_remote_first_install_requires_allow_and_placeholder_rollback(pool, tmp_path,
                                                                      monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    runner.answer("git describe", "v1.0.0")
    runner.answer(".requirements.sha", "")   # 首装:current 无基准
    runner.answer("readlink", "")            # 首装:无 current
    fake_smoke(_green_smoke())

    # 无放行:首装无基准 → 保守判依赖差异 → 中止 FAIL
    assert run_deploy(pool, _cfg(pd), t, pd) == EXIT_DEPLOY_FAILED

    # 显式放行:继续,记录含 venv 重建说明 + 上一版占位回滚
    t2 = _ticket(pool, pd)
    assert run_deploy(pool, _cfg(pd), t2, pd, allow_deps_change=True) == 0
    text = release_record_path(pd, t2.id).read_text(encoding="utf-8")
    assert DEPS_CHANGE_NOTE in text
    assert "ln -sfn releases/<上一版> current" in text


# --- .env 差异仅 key 名(F6/R9) ---------------------------------------------------


def test_remote_env_diff_keys_only_no_value_leak(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    runner.answer("git describe", "v1.2.3")
    runner.answer(".requirements.sha", requirements_sha(pd / "apps/api/requirements.txt"))
    # 远端 .env 比 example 多 NEW_TOKEN;cut -d= -f1 只回 key 名,值不出远端
    runner.answer("cut -d= -f1", "API_KEY\nDB_PASS\nNEW_TOKEN")
    runner.answer("readlink", "releases/v1.1.0")
    fake_smoke(_green_smoke())

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == 0
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert ".env 差异" in text and "NEW_TOKEN" in text
    # 对称差仅列差异 key(API_KEY/DB_PASS 两边都有,不进清单)
    assert "API_KEY" not in text
    assert "DB_PASS" not in text
    blob = text + "|".join(c for c, _ in runner.local) \
        + "|".join(c for _, _, c in runner.ssh)
    assert "super-secret-value" not in blob
    assert "another-secret" not in blob


# --- 失败路径:构建产物缺失 / ssh 失败 / 冒烟失败(F5) -----------------------------


def test_remote_dist_dir_missing_fails_with_incident(pool, tmp_path, monkeypatch):
    import shutil
    pd = _project(tmp_path)
    shutil.rmtree(pd / "apps" / "web" / "dist")   # 构建产物缺失
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    runner.answer("git describe", "v1.2.3")

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    inc = _only_incident(pool, t.id)
    assert inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert "构建产物目录不存在" in text
    assert not any("tar -czf" in c for c, _ in runner.local)  # 未到打包


def test_remote_ssh_failure_routes_to_incident(pool, tmp_path, monkeypatch):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)

    def boom(key, host, remote_cmd):
        raise RuntimeError(f"远端命令失败(exit=255): {remote_cmd}")

    monkeypatch.setattr(deploy, "_ssh_run", boom)
    monkeypatch.setattr(deploy, "_local_run",
                        lambda cmd, cwd=None: "v1.2.3" if "describe" in cmd else "")

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    inc = _only_incident(pool, t.id)
    assert inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert "远端命令失败" in text


def test_remote_smoke_failure_incident_and_rollback(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    runner.answer("git describe", "v1.2.3")
    runner.answer(".requirements.sha", requirements_sha(pd / "apps/api/requirements.txt"))
    runner.answer("readlink", "releases/v1.1.0")
    fake_smoke([
        SmokeResult(url=SMOKE_URLS[0], status=200, elapsed_ms=2, ok=True),
        SmokeResult(url=SMOKE_URLS[1], status=404, elapsed_ms=9, ok=False),
    ])

    code = run_deploy(pool, _cfg(pd), t, pd)

    assert code == EXIT_DEPLOY_FAILED
    assert any("ln -sfn releases/v1.2.3" in c for _, _, c in runner.ssh)  # 已回切重启
    inc = _only_incident(pool, t.id)
    assert inc.type == "incident" and inc.related_ticket == t.id
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert f"## {SECTION_FAILURE}" in text and inc.id in text
    assert f"## {SECTION_SMOKE}" in text and "FAIL" in text and "404" in text
    assert f"## {SECTION_ROLLBACK}" in text
    assert "ln -sfn releases/v1.1.0 current" in text  # 上一版回切可照抄
    assert RESTART in text


# --- run_deploy 分发:未登记 / local 边界 -----------------------------------------


def test_run_deploy_unregistered_writes_explicit_note(pool, tmp_path):
    pd = tmp_path / "proj-ghost"
    pd.mkdir()
    t = new_ticket(pool, project="ghost", summary="未登记 deploy", created_by="test")
    tid_dir = pd / "document" / "business" / f"{t.id}-ghost测试"
    (tid_dir / "05_部署交付").mkdir(parents=True)

    code = run_deploy(pool, {"projects": {"ghost": str(pd)}}, t, pd)  # 无 deploy 段

    assert code == 0
    text = release_record_path(pd, t.id).read_text(encoding="utf-8")
    assert UNREGISTERED_DEPLOY_NOTE in text
    assert "本单纯代码交付" in text


def test_run_deploy_local_now_dispatches_pipeline(pool, tmp_path, monkeypatch):
    """G5 交付后 local 不再 NotImplemented:run_deploy 按 local 流水线执行并全绿
    (边界验证;细节覆盖在 test_deploy_local.py)。"""
    pd = _project(tmp_path)
    t = new_ticket(pool, project="ai-factory", summary="local", created_by="test")
    tid_dir = pd / "document" / "business" / f"{t.id}-local测试"
    (tid_dir / "05_部署交付").mkdir(parents=True)
    local_cfg = {"deploy": {"ai-factory": {
        "target": "local",
        "processes": [{"name": "x", "pidfile": "x.pid", "start_cmd": "echo x"}],
        "smoke": ["http://127.0.0.1:9/"],
    }}, "projects": {"ai-factory": str(pd)}}
    # 不真杀进程/不发 HTTP:注入 fake 进程操作与冒烟(首启分支:无旧 pid)
    calls: list[tuple] = []
    monkeypatch.setattr(deploy, "_read_pid", lambda pf: None)
    monkeypatch.setattr(deploy, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(deploy, "_terminate_pid",
                        lambda pid: calls.append(("term", pid)))
    monkeypatch.setattr(deploy, "_spawn_process",
                        lambda cmd, cwd=None, log_path=None: (
                            calls.append(("spawn", cmd, str(cwd))), 9999)[1])
    monkeypatch.setattr(deploy, "_write_pid",
                        lambda pf, pid: calls.append(("write", pid)))
    monkeypatch.setattr(deploy, "_local_run",
                        lambda cmd, cwd=None: "v1.2.3" if "describe" in cmd else "")
    monkeypatch.setattr(deploy, "smoke",
                        lambda urls, *a, **k: [SmokeResult(url=urls[0], status=200,
                                                           elapsed_ms=1, ok=True)])

    code = run_deploy(pool, local_cfg, t, pd)

    assert code == 0
    assert [c[0] for c in calls] == ["spawn", "write"]   # 首启:无 terminate
    record = release_record_path(pd, t.id)
    assert record is not None and record.is_file()
    text = record.read_text(encoding="utf-8")
    assert f"## {SECTION_DEPLOY}" in text and "`local`" in text
    assert f"## {SECTION_SMOKE}" in text and "全绿" in text


# --- CLI __main__(design §接口契约) ----------------------------------------------


def test_cli_main_runs_pipeline(pool, tmp_path, monkeypatch, fake_smoke):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    runner = FakeRunner(monkeypatch)
    runner.answer("git describe", "v1.2.3")
    runner.answer(".requirements.sha", requirements_sha(pd / "apps/api/requirements.txt"))
    runner.answer("readlink", "releases/v1.1.0")
    fake_smoke(_green_smoke())
    cfg = _cfg(pd)
    cfg["pool"] = str(pool)
    monkeypatch.setattr(deploy, "_load_cfg", lambda: cfg)

    code = deploy.main([t.id])

    assert code == 0
    assert release_record_path(pd, t.id).is_file()
    assert any("ln -sfn releases/v1.2.3" in c for _, _, c in runner.ssh)


def test_cli_main_allow_deps_change_flag_passthrough(pool, tmp_path, monkeypatch):
    pd = _project(tmp_path)
    t = _ticket(pool, pd)
    captured: dict = {}
    monkeypatch.setattr(
        deploy, "run_deploy",
        lambda pool_, cfg, ticket, pd_, allow_deps_change=False:
        captured.update(tid=ticket.id, pd=str(pd_), allow=allow_deps_change) or 0)
    cfg = _cfg(pd)
    cfg["pool"] = str(pool)
    monkeypatch.setattr(deploy, "_load_cfg", lambda: cfg)

    assert deploy.main([t.id]) == 0
    assert captured["tid"] == t.id and captured["allow"] is False
    assert deploy.main([t.id, "--allow-deps-change"]) == 0
    assert captured["allow"] is True


def test_cli_main_unknown_ticket_returns_1(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_load_cfg",
                        lambda: {"pool": str(tmp_path / "ghost-pool")})
    assert deploy.main(["T-2099-0101-999"]) == 1


def test_cli_main_unregistered_project_returns_1(pool, tmp_path, monkeypatch):
    t = new_ticket(pool, project="ghost", summary="x", created_by="test")
    monkeypatch.setattr(deploy, "_load_cfg", lambda: {"pool": str(pool)})  # projects 未登记
    assert deploy.main([t.id]) == 1


def test_cli_main_local_target_returns_1_until_g5(pool, tmp_path, monkeypatch):
    pd = _project(tmp_path)
    t = new_ticket(pool, project="ai-factory", summary="local", created_by="test")
    local_cfg = {"deploy": {"ai-factory": {
        "target": "local",
        "processes": [{"name": "x", "pidfile": "x.pid", "start_cmd": "echo x"}],
        "smoke": ["http://127.0.0.1:9/"],
    }}, "projects": {"ai-factory": str(pd)}, "pool": str(pool)}
    monkeypatch.setattr(deploy, "_load_cfg", lambda: local_cfg)
    assert deploy.main([t.id]) == 1  # NotImplementedError → CLI 报错退出,不静默
