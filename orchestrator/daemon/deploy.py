"""部署单一事实源(T-2026-0901-004):config 加载校验 / smoke+差异检查 / remote+local 双流水线 /
发布记录章节写入 / 失败建 incident / CLI __main__。

G1 交付:模块骨架 + 配置 schema 加载校验(load_deploy_config);
G2 交付:冒烟检查器(smoke/smoke_passed)+ 差异检查
         (env_key_diff 仅 key 名 / requirements_sha + requirements_changed 哈希差异);
其余(remote/local 流水线、发布记录章节写入、失败建 incident、CLI)按
design §接口契约 占位(G3-G5 逐切片实现,签名与语义先钉死)。

deploy target 抽象(design Architecture):target 只有 local/remote 两形态,
差异全部沉淀为 orchestrator.yaml `deploy:` 段配置值,代码零分支判断凭证/权限形态。
sudo 卡点不进入代码:配置里就是一行 restart_cmd,决策只改编排配置不改程序。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error as _urlerror
from urllib import request as _urlrequest

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


# --- 以下为后续切片占位(design §接口契约;G3-G5 实现) -----------------------------


def run_deploy(pool, cfg: dict, ticket, project_dir: str | Path,
               allow_deps_change: bool = False) -> int:
    """部署入口(design §2/§5,G4/G5 实现):按 ticket.project 的 deploy 配置执行
    remote/local 流水线 + 冒烟 + 发布记录章节写入;返回 0=全绿;
    失败自动建 incident 工单+回链并**非零退出**(不静默放行)。"""
    raise NotImplementedError("由 G4/G5(test_deploy_remote/test_deploy_local)实现")


def main(argv: list[str] | None = None) -> int:
    """CLI(G4 实现):python -m orchestrator.daemon.deploy <tid> [--allow-deps-change];
    release 角色与人工共用同一入口。"""
    raise NotImplementedError("由 G4(test_deploy_remote)实现")


if __name__ == "__main__":
    import sys
    sys.exit(main())
