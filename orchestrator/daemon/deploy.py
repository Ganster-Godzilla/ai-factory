"""部署单一事实源(T-2026-0901-004):config 加载校验 / smoke+差异检查 / remote+local 双流水线 /
发布记录章节写入 / 失败建 incident / CLI __main__。

G1 交付:模块骨架 + 配置 schema 加载校验(load_deploy_config);
G2 交付:冒烟检查器(smoke/smoke_passed)+ 差异检查
         (env_key_diff 仅 key 名 / requirements_sha + requirements_changed 哈希差异);
G3 交付:发布记录章节写入(部署清单/冒烟结果/回滚方案)+ 冒烟失败自动建 incident
         工单+回链+非零退出(design §4,成功/失败/未登记三路径);
G4 交付:remote 流水线(design §2):本地构建→tar+ssh 上传→解包留版 chown 归一→
         依赖/.env 前置→current 回切→restart_cmd→冒烟→发布记录章节写入;
         CLI __main__(python -m orchestrator.daemon.deploy <tid> [--allow-deps-change]);
G5 交付:local 流水线(design §5):按 processes 清单逐个 pidfile 重启(读 pid →
         terminate → spawn start_cmd 并回写 pid)→ 本地冒烟 → 发布记录章节写入;
         治"合并后忘重启"病根:重启动作在脚本里,不靠人记得。

deploy target 抽象(design Architecture):target 只有 local/remote 两形态,
差异全部沉淀为 orchestrator.yaml `deploy:` 段配置值,代码零分支判断凭证/权限形态。
sudo 卡点不进入代码:配置里就是一行 restart_cmd,决策只改编排配置不改程序。
"""
from __future__ import annotations

import hashlib
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib import error as _urlerror
from urllib import request as _urlrequest

from orchestrator.daemon.artifacts import ARTIFACT_MANIFEST
from orchestrator.daemon.events import append_event

if TYPE_CHECKING:  # 仅类型标注,避免运行期依赖(events/ticket 无反向依赖)
    from orchestrator.daemon.ticket import Ticket

# --- 配置 schema(T-2026-0901-004 design §1) ---

VALID_TARGETS = ("local", "remote")

# remote 必填键:缺任一即无法完成"上传→解包→重启→冒烟"契约;
# service/build_cmd/dist_dir 可选(纯后端项目可无前端构建)。
_REMOTE_REQUIRED = ("host", "ssh_key", "app_dir", "restart_cmd", "smoke",
                    "requirements", "env_example", "remote_env")
_REMOTE_OPTIONAL = ("service", "build_cmd", "dist_dir")

# local 必填键
_LOCAL_REQUIRED = ("processes", "smoke")
_PROCESS_REQUIRED = ("name", "pidfile", "start_cmd")

# 需要本地文件存在的路径键(相对项目 checkout 解析;加载时即校验,design §1 校验规则)。
# ssh_key 属部署时凭证,不在此校验(可能只存在于发布机);dist_dir 是构建产物,
# 构建前不存在,交给流水线检查。
_REMOTE_LOCAL_FILES = ("requirements", "env_example")


@dataclass
class SmokeResult:
    """单 URL 冒烟留痕(design §3;G2 实现 smoke())。"""
    url: str
    status: int | None
    elapsed_ms: int
    ok: bool


def _fmt(project: str, msg: str) -> str:
    return f"deploy.{project}: {msg}"


def load_deploy_config(cfg: dict, project: str,
                       project_dir: str | Path | None = None) -> dict | None:
    """加载并校验 project 的 deploy 配置(design §1);未登记 → None,非法配置抛 ValueError。

    校验规则(target/必填键/类型/路径存在性)在加载时完成,响亮报错:
    - target 必须是 {"local", "remote"} 之一
    - 必填键缺失(remote: host/ssh_key/app_dir/restart_cmd/smoke/requirements/
      env_example/remote_env;local: processes/smoke)
    - smoke 非空 URL 列表;local processes 每项含 name/pidfile/start_cmd
    - 路径存在性:remote 的 requirements/env_example 是本地基准文件,须在项目
      checkout 下真实存在(相对 project_dir 解析)

    project_dir 缺省时从 cfg["projects"] 反查(gates.project_dir_for 同源);
    两者都拿不到则跳过路径存在性检查(纯结构校验)。
    """
    deploy = cfg.get("deploy")
    if not isinstance(deploy, dict) or project not in deploy:
        return None
    conf = deploy[project]
    if not isinstance(conf, dict):
        raise ValueError(_fmt(project, f"配置必须是映射(dict),实际 {type(conf).__name__}"))

    target = conf.get("target")
    if target not in VALID_TARGETS:
        raise ValueError(_fmt(
            project, f"target 非法: {target!r}(合法值: {', '.join(VALID_TARGETS)})"))

    required = _REMOTE_REQUIRED if target == "remote" else _LOCAL_REQUIRED
    missing = [k for k in required if k not in conf]
    if missing:
        raise ValueError(_fmt(
            project, f"{target} 形态缺必填键: {', '.join(missing)}"))

    # --- 类型/结构校验 ---
    _check_smoke(project, conf.get("smoke"))
    if target == "remote":
        for k in _REMOTE_REQUIRED + _REMOTE_OPTIONAL:
            if k in conf and k != "smoke":
                _check_str(project, k, conf[k])
    else:
        _check_processes(project, conf.get("processes"))

    # --- 路径存在性(本地基准文件) ---
    if target == "remote":
        pd = project_dir
        if pd is None:
            registered = (cfg.get("projects") or {}).get(project)
            pd = Path(registered) if registered else None
        if pd is not None:
            base = Path(pd)
            for k in _REMOTE_LOCAL_FILES:
                if k not in conf:
                    continue
                p = base / conf[k]
                if not p.is_file():
                    raise ValueError(_fmt(
                        project, f"{k} 指向的本地文件不存在: {p}(相对项目 checkout 解析)"))

    return conf


def _check_str(project: str, key: str, value) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_fmt(project, f"{key} 必须是非空字符串,实际 {value!r}"))


def _check_smoke(project: str, smoke) -> None:
    if not isinstance(smoke, list) or not smoke:
        raise ValueError(_fmt(project, "smoke 必须是非空 URL 列表"))
    for u in smoke:
        if not isinstance(u, str) or not (u.startswith("http://")
                                          or u.startswith("https://")):
            raise ValueError(_fmt(project, f"smoke 条目必须是 http(s) URL,实际 {u!r}"))


def _check_processes(project: str, processes) -> None:
    if not isinstance(processes, list) or not processes:
        raise ValueError(_fmt(project, "processes 必须是非空列表(长驻进程清单)"))
    for i, proc in enumerate(processes):
        if not isinstance(proc, dict):
            raise ValueError(_fmt(project, f"processes[{i}] 必须是映射,实际 {type(proc).__name__}"))
        for k in _PROCESS_REQUIRED:
            if k not in proc:
                raise ValueError(_fmt(project, f"processes[{i}] 缺必填键: {k}"))
            _check_str(project, f"processes[{i}].{k}", proc[k])


# --- G2 交付:冒烟检查器 + 差异检查(design §3 / §2.4 / §2.3) -----------------------

# 重试退避基准(秒):第 n 次重试前等待 n * base(线性退避)。真实部署单 URL 最坏
# 4 次尝试累计等待 1+2+3=6 秒;单测 monkeypatch deploy._sleep 注入假时钟,不真实等待。
_RETRY_BACKOFF_BASE = 1.0
_HTTP_TIMEOUT = 5.0

# 模块级 sleep 间接层:单测 monkeypatch 为记录器/空操作,避免用例真实睡 6 秒。
_sleep = time.sleep


def smoke(urls: list[str], expect: int = 200, retries: int = 3,
          timeout: float = _HTTP_TIMEOUT) -> list[SmokeResult]:
    """冒烟检查器(design §3):对配置 smoke URL 逐个 GET,期望 expect(默认 200),
    失败重试至多 retries 次(线性退避),结果(URL/状态码/耗时)全量留痕。

    判定语义:某 URL 任一尝试返回期望码即 ok=True;retries 用尽仍非期望码或
    连接失败(status=None)即 ok=False。任一非 200 即整体失败,由调用方经
    ok 字段 / smoke_passed() 判读。timeout:单次 GET 超时秒数,连接挂死不无限等;
    HTTP 错误码与连接类异常(URLError/OSError/超时)一律视为失败并参与重试。"""
    results: list[SmokeResult] = []
    for url in urls:
        t0 = time.perf_counter()
        last_status: int | None = None
        ok = False
        for attempt in range(retries + 1):  # 首次 + retries 次重试
            last_status = _fetch_status(url, timeout=timeout)
            if last_status == expect:
                ok = True
                break
            if attempt < retries:  # 还有重试机会:退避后重试
                _sleep(_RETRY_BACKOFF_BASE * (attempt + 1))
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        results.append(SmokeResult(
            url=url, status=(expect if ok else last_status),
            elapsed_ms=elapsed_ms, ok=ok))
    return results


def _fetch_status(url: str, timeout: float) -> int | None:
    """单次 GET 的状态码;连接类失败返回 None(不抛,交给重试循环)。"""
    try:
        with _urlrequest.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except _urlerror.HTTPError as e:  # 4xx/5xx:有状态码,失败但可记录
        return e.code
    except (_urlerror.URLError, OSError, TimeoutError):
        return None


def smoke_passed(results: list[SmokeResult]) -> bool:
    """全 200 判定(design §3 任一非 200 即整体失败):全部 ok 才 True;
    空清单(无冒烟证据)保守判 False。"""
    return bool(results) and all(r.ok for r in results)


def env_key_diff(example_path: str | Path, remote_keys: set[str]) -> list[str]:
    """.env 差异检查(design §2.4):本地 env_example 的 key 集合与远端回传的
    key 名集合求对称差,差异清单仅 key 名、按名排序;值永不回传/入输出/记录
    (R9 密钥不落库)——本函数只产出 key 名,调用方不得把值带进部署单。

    example 解析规则:跳过空行与 # 注释行;可带 export 前缀;key=第一个 '=' 前
    的 stripped 段;无 '=' 的行整行视为 key。基准文件缺失直接抛
    FileNotFoundError(加载期已校验存在性,缺失属状态异常)。"""
    example_keys = _parse_env_keys(Path(example_path).read_text(encoding="utf-8"))
    return sorted(example_keys ^ set(remote_keys))


def _parse_env_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def requirements_sha(local_path: str | Path) -> str:
    """本地 requirements 文件 sha256(依赖差异前置检查基准,design §2.3)。
    基准文件加载期已校验存在性,缺失直接抛 FileNotFoundError。"""
    return hashlib.sha256(Path(local_path).read_bytes()).hexdigest()


def requirements_changed(local_path: str | Path, remote_sha: str | None) -> bool:
    """依赖差异判定(design §2.3):本地 requirements 哈希 vs 远端
    releases/current/.requirements.sha 内容;不一致即 True(部署中止条件,
    G4 流水线据此 FAIL,或 --allow-deps-change 显式放行并写 venv 重建说明)。

    远端无基准(None/空/首装无 current)→ True:无从比对即保守视为有差异,
    须显式处置(首装按依赖变更放行)。"""
    local = requirements_sha(local_path)
    baseline = (remote_sha or "").strip()
    return not baseline or local != baseline


# --- G3 交付:发布记录章节写入 + 失败建 incident(design §4;F4/F5) ------------------

# 发布记录文件路径模板:与 artifacts.py P5_RELEASE 同源(单一事实源,门禁口径一致)。
# 未登记 deploy 的项目也写"部署清单"章节(design §4:章节仍在,语义由审批人复核)。
_RELEASE_RECORD_TEMPLATE = ARTIFACT_MANIFEST["P5_RELEASE"]["artifacts"][0]["path"]

# 发布记录章节名(与 P5_RELEASE require_sections 对齐,勿改字面)
SECTION_DEPLOY = "部署清单"
SECTION_SMOKE = "冒烟结果"
SECTION_ROLLBACK = "回滚方案"
SECTION_FAILURE = "部署失败"

# 部署/冒烟失败退出码:非零即判负,release 角色(dsh)走既有 release_failed 挂起,
# 不静默放行(design §4)。
EXIT_DEPLOY_FAILED = 1

# 未登记 deploy 配置项目的显式声明文本(design §4)
UNREGISTERED_DEPLOY_NOTE = "未登记 deploy,本单纯代码交付"


def release_record_path(project_dir: str | Path, ticket_id: str) -> Path | None:
    """发布记录文件路径(design §4):复用 artifacts.P5_RELEASE 路径模板解析
    {tid_dir}(工单文件夹多匹配取字典序首个,与门禁解析同源);
    工单文件夹未建/解析失败 → None(调用方按"记录不可写"处理,失败路径不因此中断)。"""
    from orchestrator.daemon.artifacts import resolve_artifact_path
    rel = resolve_artifact_path(Path(project_dir), _RELEASE_RECORD_TEMPLATE, ticket_id)
    return Path(project_dir) / rel if rel else None


def write_release_record(path: str | Path, sections: list[str],
                         title: str = "发布记录") -> Path:
    """发布记录章节写入(design §4):把 sections(部署清单/冒烟结果/回滚方案等
    markdown 章节文本)追加写入发布记录文件;文件不存在先写标题行再追加
    (发布员先写合并清单/版本、deploy 脚本补部署三章,先后顺序不敏感)。
    返回写入路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_file = not p.exists()
    with p.open("a", encoding="utf-8", newline="\n") as f:
        if new_file:
            f.write(f"# {title}\n\n")
        for section in sections:
            f.write(section.rstrip("\n") + "\n\n")
    return p


def render_deploy_manifest(*, version: str, target: str, when: str,
                           deps_note: str | None = None,
                           env_diff: list[str] | None = None,
                           processes_note: str | None = None) -> str:
    """部署清单章节(design §4 成功路径):版本/目标/时间 + 依赖与 .env 差异清单
    (remote)+ 重启进程留痕(local)。env_diff 仅 key 名(值永不入记录/输出,
    R9 密钥不落库);None=未检查(省略该行)。"""
    lines = [f"## {SECTION_DEPLOY}", "",
             f"- 版本:`{version}`",
             f"- 目标:`{target}`",
             f"- 时间:`{when}`"]
    if deps_note is not None:
        lines.append(f"- 依赖差异:{deps_note}")
    if env_diff is not None:
        if env_diff:
            lines.append(f"- .env 差异(仅 key 名):`{', '.join(sorted(env_diff))}`")
        else:
            lines.append("- .env 差异:无")
    if processes_note is not None:
        lines.append(f"- 重启进程:{processes_note}")
    return "\n".join(lines) + "\n"


def render_unregistered_deploy() -> str:
    """未登记 deploy 配置项目的部署清单章节(design §4):显式声明
    '未登记 deploy,本单纯代码交付',章节仍在,语义由审批人复核。"""
    return f"## {SECTION_DEPLOY}\n\n- {UNREGISTERED_DEPLOY_NOTE}\n"


def render_smoke_section(results: list[SmokeResult]) -> str:
    """冒烟结果章节(design §3):每个 URL 的状态码/耗时全量留痕 + 总体判定
    (任一非 200 即整体失败)。"""
    lines = [f"## {SECTION_SMOKE}", ""]
    for r in results:
        status = str(r.status) if r.status is not None else "连接失败"
        verdict = "PASS" if r.ok else "FAIL"
        lines.append(f"- `{r.url}` → {status}, {r.elapsed_ms}ms → {verdict}")
    verdict = "全绿,发布成功" if smoke_passed(results) else "存在失败,发布失败"
    lines += ["", f"**总体判定:{verdict}**"]
    return "\n".join(lines) + "\n"


def rollback_plan(conf: dict, prev_version: str | None = None,
                  restart_cmd: str | None = None) -> str:
    """回滚方案章节(design §4):自动生成可照抄命令。
    remote=回切上一版包 + 重启:`ln -sfn releases/<上一版> current && <restart_cmd>`
    (上一版包逐版留存于 releases/,回滚不依赖远端在否);
    local=git tag 回切 + 长驻进程逐条重启。版本未知用占位符,人工补齐即可照抄。"""
    target = conf.get("target")
    if target == "remote":
        prev = prev_version or "<上一版>"
        cmd = restart_cmd or conf.get("restart_cmd") or "<restart_cmd>"
        lines = [f"## {SECTION_ROLLBACK}", "",
                 "1. 回切上一版包并重启(命令可照抄):",
                 f"   `ln -sfn releases/{prev} current && {cmd}`",
                 "2. 按部署冒烟清单复验,全 200 才算回滚成功"]
    else:
        prev = prev_version or "<上一 tag>"
        lines = [f"## {SECTION_ROLLBACK}", "",
                 f"1. git tag 回切(命令可照抄):`git checkout {prev}`",
                 "2. 重启长驻进程(逐条可照抄):"]
        for proc in conf.get("processes", []):
            lines.append(f"   - {proc.get('name', '?')}:`{proc.get('start_cmd')}`")
        lines.append("3. 按部署冒烟清单复验,全 200 才算回滚成功")
    return "\n".join(lines) + "\n"


def create_incident(pool: Path, ticket, summary: str) -> "Ticket":
    """冒烟/部署失败自动建 incident 工单(design §4):new_ticket(type=incident,
    related_ticket=原单) + 原单事件流 incident_created 回链——与 runner.py
    release 判负同模式:事故单 related_ticket 与原单 incident_created 双向可查。
    返回新事故单。"""
    from orchestrator.daemon.ticket import new_ticket
    inc = new_ticket(pool, ticket.project, summary,
                     created_by="system", type="incident",
                     related_ticket=ticket.id)
    append_event(pool, ticket.id, "system", "incident_created", incident=inc.id)
    return inc


def handle_deploy_failure(pool: Path, ticket, project_dir: str | Path,
                          conf: dict, *, results: list[SmokeResult] | None = None,
                          detail: str | None = None,
                          rollback: str | None = None) -> int:
    """失败处置(design §4):自动建 incident 工单(related_ticket=原单)+ 原单
    incident_created 回链 + 发布记录写失败详情与回滚说明;返回非零退出码
    EXIT_DEPLOY_FAILED——release 角色(dsh)判负走既有 release_failed 挂起,
    不静默放行。results=冒烟结果留痕;detail=失败详情文本;rollback=回滚说明
    (缺省按 conf 自动生成 rollback_plan;版本未知时占位符,人工补齐)。"""
    inc = create_incident(pool, ticket, f"部署/冒烟失败:{ticket.id} {ticket.summary}")
    blocks = [
        f"## {SECTION_FAILURE}",
        f"- 事故单:`{inc.id}`(type=incident, related_ticket 回链原单 `{ticket.id}`)",
    ]
    if detail:
        blocks.append(detail)
    if results:
        blocks.append(render_smoke_section(results))
    blocks.append(rollback if rollback is not None else rollback_plan(conf))
    record = release_record_path(project_dir, ticket.id)
    if record is not None:
        write_release_record(record, blocks,
                             title=f"发布记录:{ticket.id}(部署失败)")
    return EXIT_DEPLOY_FAILED


# --- G4 交付:remote 流水线 + CLI(design §2 / §接口契约) -------------------------

# 依赖差异显式放行后,发布记录必写的 venv 重建说明(服务器不现场装依赖,歧义澄清已定)
DEPS_CHANGE_NOTE = ("依赖有差异,已按 --allow-deps-change 显式放行;"
                    "需在发布机重建 venv 并随包上传,服务器不现场装依赖")


def _local_run(cmd: str, cwd: str | Path | None = None) -> str:
    """本地命令执行(返回 stdout,非零退出抛 RuntimeError)。
    命令序列统一走本函数:G4 单测以 fake runner monkeypatch 记录并断言,
    不真跑 tar/scp/ssh。"""
    proc = subprocess.run(cmd, shell=True,
                          cwd=str(cwd) if cwd is not None else None,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"本地命令失败(exit={proc.returncode}): {cmd}")
    return proc.stdout.strip()


def _ssh_run(ssh_key: str, host: str, remote_cmd: str) -> str:
    """远端命令执行(ssh -i key host <cmd>;BatchMode 免交互、accept-new 首连),
    返回 stdout;非零退出抛 RuntimeError。单测同样以 fake runner monkeypatch。"""
    args = ["ssh", "-i", str(Path(ssh_key).expanduser()),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            host, remote_cmd]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"远端命令失败(exit={proc.returncode}): {remote_cmd}")
    return proc.stdout.strip()


def _git_describe(project_dir: str | Path) -> str:
    """版本号(design §2):项目仓 `git describe --tags --always`,空输出判异常。"""
    out = _local_run("git describe --tags --always", cwd=project_dir)
    if not out:
        raise RuntimeError("git describe 无输出,无法确定发布版本")
    return out


def _run_remote(pool: Path, conf: dict, ticket, project_dir: str | Path,
                allow_deps_change: bool) -> int:
    """remote 流水线(design §2):本地构建→tar+ssh 上传→解包留版 chown 归一→
    依赖/.env 前置→current 回切→restart_cmd→冒烟→发布记录章节写入。

    返回 0=全绿;任一步骤失败(含依赖差异未放行、冒烟非全绿)自动建 incident
    工单+回链并返回 EXIT_DEPLOY_FAILED(不静默放行)。"""
    pd = Path(project_dir)
    app = conf["app_dir"].rstrip("/")
    key, host, restart = conf["ssh_key"], conf["host"], conf["restart_cmd"]
    try:
        ver = _git_describe(pd)

        # 1. 本地构建(build_cmd 可选:纯后端项目无前端构建;dist_dir 产物存在性检查)
        if conf.get("build_cmd"):
            _local_run(conf["build_cmd"], cwd=pd)
        if conf.get("dist_dir") and not (pd / conf["dist_dir"]).is_dir():
            raise RuntimeError(
                f"构建产物目录不存在: {pd / conf['dist_dir']}(先跑 build_cmd 或核对 dist_dir)")

        # 2. tar.gz 打包:整仓快照(排除 .git),dist+后端代码同包(design §2.1)
        bundle = Path(tempfile.gettempdir()) / f"orc-deploy-{ticket.project}-{ver}.tar.gz"
        _local_run(f"tar -czf {bundle} -C {pd} --exclude=.git .")

        # 3. 上传 + 远端解包留版 + chown uid 归一(F2 坑:属主归一为发布账号)
        _ssh_run(key, host, f"mkdir -p {app}/releases")
        _local_run(f"scp -i {key} {bundle} {host}:{app}/releases/{ver}.tar.gz")
        _ssh_run(key, host,
                 f"mkdir -p {app}/releases/{ver} && "
                 f"tar -xzf {app}/releases/{ver}.tar.gz -C {app}/releases/{ver} && "
                 f"rm -f {app}/releases/{ver}.tar.gz && "
                 f"chown -R \"$(id -u):$(id -g)\" {app}/releases/{ver}")

        # 4. 依赖差异前置检查(design §2.3):本地 requirements 哈希 vs 远端
        #    releases/current/.requirements.sha;不一致即中止 FAIL,除非显式放行
        remote_sha = _ssh_run(key, host,
                              f"test -f {app}/releases/current/.requirements.sha "
                              f"&& cat {app}/releases/current/.requirements.sha || echo ''")
        local_sha = requirements_sha(pd / conf["requirements"])
        deps_changed = requirements_changed(pd / conf["requirements"], remote_sha or None)
        if deps_changed and not allow_deps_change:
            detail = (f"依赖差异中止:本地 {conf['requirements']} sha={local_sha} 与远端 "
                      f"releases/current/.requirements.sha={remote_sha or '<无基准>'} 不一致。"
                      f"处置:发布单显式声明依赖变更处置(发布机重建 venv 随包上传,"
                      f"服务器不现场装依赖)后以 --allow-deps-change 放行;或先单独更新依赖。")
            return handle_deploy_failure(pool, ticket, pd, conf, detail=detail)

        # 5. 记录本次发布依赖基准(下次部署以本版为准比对)
        _ssh_run(key, host, f"echo {local_sha} > {app}/releases/{ver}/.requirements.sha")

        # 6. .env 差异检查(design §2.4):远端只回传 key 名(cut -d= -f1),
        #    值不出远端/输出/记录(R9 密钥不落库)
        remote_keys = _ssh_run(key, host,
                               f"test -f {conf['remote_env']} "
                               f"&& cut -d= -f1 {conf['remote_env']} || echo ''")
        env_diff = env_key_diff(pd / conf["env_example"], _parse_env_keys(remote_keys))

        # 7. 回滚基准:回切前记下 current 指向的上一版(首装无 current → 占位符)
        cur = _ssh_run(key, host,
                       f"test -L {app}/current && readlink {app}/current || echo ''")
        prev_version = Path(cur).name if cur else None

        # 8. current 回切 + 执行 restart_cmd(design §2.5)
        _ssh_run(key, host, f"ln -sfn releases/{ver} {app}/current && {restart}")

        # 9. 冒烟(design §3)
        results = smoke(conf["smoke"])
        if not smoke_passed(results):
            # 失败记录的回滚说明带上具体上一版(回切前已读到),可照抄执行
            rollback = rollback_plan(conf, prev_version=prev_version, restart_cmd=restart)
            return handle_deploy_failure(pool, ticket, pd, conf, results=results,
                                         rollback=rollback)

        # 10. 发布记录章节写入(design §4 成功路径):部署清单/冒烟结果/回滚方案
        deps_note = (DEPS_CHANGE_NOTE if deps_changed and allow_deps_change
                     else "无差异(与 releases/current 基准一致)")
        manifest = render_deploy_manifest(
            version=ver, target="remote", when=datetime.now(timezone.utc).isoformat(),
            deps_note=deps_note, env_diff=env_diff)
        rollback = rollback_plan(conf, prev_version=prev_version, restart_cmd=restart)
        record = release_record_path(pd, ticket.id)
        if record is not None:
            write_release_record(record,
                                 [manifest, render_smoke_section(results), rollback],
                                 title=f"发布记录:{ticket.id}")
        return 0
    except Exception as e:  # noqa: BLE001 — 构建/打包/上传/ssh 任一环节失败:不静默
        return handle_deploy_failure(pool, ticket, pd, conf, detail=str(e))


# --- G5 交付:local 流水线(design §5;F7) -----------------------------------------

# 长驻进程 graceful terminate 后等待退出的上限(秒);超时升级 SIGKILL。
# 等退出而非立刻 spawn:旧进程未释放端口(如 dashboard 8765)时新进程会绑定失败。
_LOCAL_TERMINATE_TIMEOUT = 5.0

# 本地长驻进程运行时目录名(pidfile/日志落点;gitignore 已忽略,不脏仓库)。
# pidfile 路径本身来自配置(相对项目 checkout 解析);日志固定落此目录 <name>.log。
_LOCAL_RUNTIME_DIR = ".orc-local"


def _local_runtime_dir(project_dir: str | Path) -> Path:
    """本地长驻进程运行时目录(项目 checkout 下 .orc-local)。"""
    return Path(project_dir) / _LOCAL_RUNTIME_DIR


def _local_pidfile_path(project_dir: str | Path, pidfile: str) -> Path:
    """pidfile 路径解析:绝对路径原样(配置即完整路径);相对路径按项目 checkout
    解析(与部署配置同基准,design §1 路径约定)。"""
    p = Path(pidfile).expanduser()
    return p if p.is_absolute() else Path(project_dir) / p


def _read_pid(pidfile: str | Path) -> int | None:
    """读 pidfile:文件缺失/内容非纯数字 → None(首启无旧进程/陈旧内容,
    静默跳过,不报错——deploy 重启语义是幂等起步)。"""
    try:
        text = Path(pidfile).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def _pid_alive(pid: int) -> bool:
    """pid 是否存活(跨平台):posix kill(pid, 0);Windows OpenProcess 查询
    退出码 == STILL_ACTIVE。进程不存在/句柄拿不到 → False(陈旧 pid 正常路径)。"""
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权限查看:按存活处理(保守)
    return True


def _pid_alive_windows(pid: int) -> bool:
    """Windows 存活判定:OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) +
    GetExitCodeProcess == STILL_ACTIVE(259);拿不到句柄即不存活。"""
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                           False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _terminate_pid(pid: int, timeout: float = _LOCAL_TERMINATE_TIMEOUT) -> None:
    """terminate 进程(pid):先 SIGTERM,timeout 内未退出升级 SIGKILL;Windows 上
    TerminateProcess 即强杀,无 SIGTERM/SIGKILL 之分。进程不存在/已退出 →
    幂等跳过(陈旧 pid 是正常路径,不报错)。"""
    if not _pid_alive(pid):
        return
    if os.name == "nt":
        _terminate_pid_windows(pid)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return  # 竞态:刚退出/无权限,交由存活判定兜底
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        _sleep(0.1)
    if os.name != "nt":  # posix 仍存活:升级 SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _terminate_pid_windows(pid: int) -> None:
    """Windows 终止:OpenProcess(PROCESS_TERMINATE)+ TerminateProcess。
    os.kill 内部 OpenProcess(PROCESS_ALL_ACCESS) 在受限令牌/沙箱下会被拒
    (Access denied);最小权限句柄(PROCESS_TERMINATE)通常放行,等效强杀。"""
    import ctypes
    PROCESS_TERMINATE = 0x0001
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return  # 句柄拿不到(刚退出/受限):幂等跳过,存活判定兜底
    try:
        ctypes.windll.kernel32.TerminateProcess(h, 15)
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _spawn_process(start_cmd: str, cwd: str | Path,
                   log_path: str | Path | None = None) -> int:
    """spawn start_cmd 为长驻进程(脱离父进程,stdout/stderr 落 log_path),
    返回新 pid。命令按 shell 分词直接执行、不套 shell 包装:返回 pid 即真实
    进程,后续 pidfile 重启可准确 terminate(需 shell 特性时由 start_cmd
    自行包装,如 sh -c '...');分词失败(引号不成对)退化为 shell 原样执行。"""
    try:
        argv = shlex.split(start_cmd)
    except ValueError:
        argv = None  # 引号不成对:shell 原样执行(pid 为 shell 包装进程,重启语义降级)
    log = Path(log_path) if log_path else None
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # 脱离控制终端,父进程退出不影响
    with (log.open("ab") if log is not None else open(os.devnull, "ab")) as out:
        if argv is None:
            proc = subprocess.Popen(start_cmd, shell=True, cwd=str(cwd),
                                    stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=out, **kwargs)
        else:
            proc = subprocess.Popen(argv, cwd=str(cwd),
                                    stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=out, **kwargs)
    return proc.pid


def _write_pid(pidfile: str | Path, pid: int) -> None:
    """回写新 pid 到 pidfile(重启留痕;供下次 deploy 与人工查状态)。"""
    p = Path(pidfile)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{pid}\n", encoding="utf-8")


def restart_local_process(project_dir: str | Path, proc: dict) -> dict:
    """单条长驻进程重启(design §5,F7):pidfile 读 pid → 存活则 terminate
    (等退出,超时 SIGKILL)→ spawn start_cmd(长驻,输出落 .orc-local/<name>.log)
    → 回写新 pid。返回留痕 {name, old_pid, pid}(old_pid=None=首启/陈旧)。"""
    name = proc["name"]
    pidfile = _local_pidfile_path(project_dir, proc["pidfile"])
    old_pid = _read_pid(pidfile)
    if old_pid is not None and _pid_alive(old_pid):
        _terminate_pid(old_pid)
    new_pid = _spawn_process(proc["start_cmd"], cwd=project_dir,
                             log_path=_local_runtime_dir(project_dir) / f"{name}.log")
    _write_pid(pidfile, new_pid)
    return {"name": name, "old_pid": old_pid, "pid": new_pid}


def _run_local(pool, conf: dict, ticket, project_dir: str | Path) -> int:
    """local 流水线(design §5):按 processes 清单逐个重启 → 本地冒烟 →
    写发布记录(部署清单/冒烟结果/回滚方案)。治"合并后忘重启"病根:
    重启动作在脚本里,不靠人记得。返回 0=全绿;进程重启或冒烟任一失败
    自动建 incident 工单+回链并返回 EXIT_DEPLOY_FAILED(不静默放行)。"""
    pd = Path(project_dir)
    try:
        ver = _git_describe(pd)
        restarts = [restart_local_process(pd, proc) for proc in conf["processes"]]
        results = smoke(conf["smoke"])
        if not smoke_passed(results):
            return handle_deploy_failure(pool, ticket, pd, conf, results=results)
        processes_note = "; ".join(
            f"{r['name']}({'旧 pid ' + str(r['old_pid']) if r['old_pid'] else '首启'}"
            f" → 新 pid {r['pid']})" for r in restarts)
        manifest = render_deploy_manifest(
            version=ver, target="local",
            when=datetime.now(timezone.utc).isoformat(),
            processes_note=processes_note)
        rollback = rollback_plan(conf)  # local 回滚 = git tag 回切 + 逐条重启(占位 tag 人工补齐)
        record = release_record_path(pd, ticket.id)
        if record is not None:
            write_release_record(record,
                                 [manifest, render_smoke_section(results), rollback],
                                 title=f"发布记录:{ticket.id}")
        return 0
    except Exception as e:  # noqa: BLE001 — 版本/重启/冒烟任一环节失败:不静默
        return handle_deploy_failure(pool, ticket, pd, conf, detail=str(e))


def run_deploy(pool, cfg: dict, ticket, project_dir: str | Path,
               allow_deps_change: bool = False) -> int:
    """部署入口(design §2/§5):按 ticket.project 的 deploy 配置执行 remote/local
    流水线 + 冒烟 + 发布记录章节写入;返回 0=全绿;失败自动建 incident 工单+回链并
    **非零退出**(不静默放行)。未登记 deploy 配置:部署清单章节写显式声明
    '未登记 deploy,本单纯代码交付' 并返回 0(纯代码交付,语义由审批人复核)。"""
    conf = load_deploy_config(cfg, ticket.project, project_dir=project_dir)
    if conf is None:
        record = release_record_path(project_dir, ticket.id)
        if record is not None:
            write_release_record(record, [render_unregistered_deploy()],
                                 title=f"发布记录:{ticket.id}")
        return 0
    if conf["target"] == "remote":
        return _run_remote(pool, conf, ticket, project_dir, allow_deps_change)
    return _run_local(pool, conf, ticket, project_dir)


def _load_cfg() -> dict:
    """CLI 配置加载(orchestrator.yaml,与 cli.py 同约定);单测 monkeypatch 注入测试配置。"""
    import yaml
    return yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """CLI(design §接口契约):python -m orchestrator.daemon.deploy <tid> [--allow-deps-change];
    release 角色与人工共用同一入口,返回部署退出码(0=全绿)。"""
    import argparse
    from orchestrator.daemon.gates import project_dir_for
    from orchestrator.daemon.ticket import load_ticket

    p = argparse.ArgumentParser(
        prog="python -m orchestrator.daemon.deploy",
        description="按 ticket.project 的 deploy 配置执行部署+冒烟(T-2026-0901-004)")
    p.add_argument("tid", help="工单 id(T-YYYY-MMDD-NNN)")
    p.add_argument("--allow-deps-change", action="store_true",
                   help="依赖差异显式放行:发布记录必写 venv 重建说明"
                        "(服务器不现场装依赖,歧义澄清已定)")
    args = p.parse_args(argv)

    cfg = _load_cfg()
    pool = Path(cfg.get("pool", "pool"))
    try:
        ticket = load_ticket(pool, args.tid)
    except Exception as e:  # noqa: BLE001 — 工单缺失/损坏:CLI 报错退出,不 traceback
        print(f"error: 加载工单 {args.tid} 失败: {e}", file=sys.stderr)
        return 1
    pd = project_dir_for(cfg, ticket.project)
    if pd is None:
        print(f"error: 项目 {ticket.project} 未在 orchestrator.yaml projects 登记,无法部署",
              file=sys.stderr)
        return 1
    try:
        return run_deploy(pool, cfg, ticket, pd,
                          allow_deps_change=args.allow_deps_change)
    except ValueError as e:  # 配置非法等:响亮报错
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
