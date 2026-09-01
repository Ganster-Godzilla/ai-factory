"""部署单一事实源(T-2026-0901-004):config 加载校验 / smoke+差异检查 / remote+local 双流水线 /
发布记录章节写入 / 失败建 incident / CLI __main__。

G1 交付:模块骨架 + 配置 schema 加载校验(load_deploy_config);
其余公开函数按 design §接口契约 占位(G2-G5 逐切片实现,签名与语义先钉死)。

deploy target 抽象(design Architecture):target 只有 local/remote 两形态,
差异全部沉淀为 orchestrator.yaml `deploy:` 段配置值,代码零分支判断凭证/权限形态。
sudo 卡点不进入代码:配置里就是一行 restart_cmd,决策只改编排配置不改程序。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


# --- 以下为后续切片占位(design §接口契约;G2-G5 实现) -----------------------------


def smoke(urls: list[str], expect: int = 200, retries: int = 3) -> list[SmokeResult]:
    """冒烟检查器(design §3,G2 实现):对配置 smoke URL 逐个 GET 期望 expect,
    失败重试 retries 次(间隔退避),结果(URL/状态码/耗时)全量留痕;
    任一非期望码即整体失败(由调用方判读 ok 字段)。"""
    raise NotImplementedError("由 G2(test_deploy_smoke)实现")


def env_key_diff(example_path: str | Path, remote_keys: set[str]) -> list[str]:
    """.env 差异检查(design §2.4,G2 实现):本地 env_example 的 key 集合与远端
    回传的 key 名集合(仅 key 名)求差;值永不回传/入任何输出/记录/事件流(R9)。"""
    raise NotImplementedError("由 G2(test_deploy_smoke)实现")


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
