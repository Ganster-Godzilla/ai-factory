"""gitguard:loop 合 main 前置守卫(T-2026-0902-006)。

堵 dev-loop「切片即合 main」快道(规则#11)的合 main 盲区:loop 合 main 前会把
main 同步回 origin/main(重置类操作),工作区里他人未推送提交/未提交改动会被
静默丢弃(2026-09-01 实证:SOP 文档提交未入任何历史)。守卫 = 合 main 前置闸:

    1. fetch origin(最佳努力:离线/无 remote 不阻断,用本地既有 origin/main);
    2. `git log origin/main..HEAD` 非空且存在非 loop 签名白名单前缀的提交 → 拦截
       (清单指名 hash/作者/时间/首行);白名单 = 工单号前缀 + loop 模式,
       识别不了的一律视为他人(宁可误拦);
    3. `git status --porcelain` 非空(工作区/索引脏,含未跟踪)→ 拦截;
       .orc-base 是编排器记号(ensure_worktree 落盘),不算他人改动,不计入
       (口径与 runner._changed_files 一致)。

纯增量:新模块 + 新 CLI 动词 + 指南/提示词文本,revert 即回滚;
release 角色 P5 审批链与 worktree 机制不动。

用法(经 CLI):
    python -m orchestrator.daemon.cli guard pre-merge <project_dir>
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# loop 签名白名单(design 默认):提交首行命中任一前缀 = loop/工单线自建,放行。
# merge(S/chore(S 命中 dev-loop 切片签名;merge(orc/ 命中 worktree 分支合入;
# merge(T-/fix(T-/feat(T-/docs(T-/release(T- 命中工单号线提交。
DEFAULT_ALLOWED_PREFIXES = (
    "merge(orc/", "merge(S", "chore(S", "merge(T-", "fix(T-", "feat(T-",
    "docs(T-", "release(T-",
)

# 编排器记号文件:worktree 的 .orc-base 由 ensure_worktree 创建时落盘(scope
# 越界检查的 diff 基线),是运行器书签而非他人改动——脏树检查不计入。
IGNORED_DIRTY_PATHS = frozenset({".orc-base"})

# fetch 最佳努力:失败/超时只放弃刷新,不阻断检查(守卫宁可用陈旧 origin/main,
# 多拦不可放——方向是安全的)。
_FETCH_TIMEOUT_S = 60
# git log 单行字段:hash/作者/ISO 时间/首行;`%x1f` 分隔,避免与正文内容相撞
_FIELD_SEP = "\x1f"
_LOG_FORMAT = f"%H{_FIELD_SEP}%an{_FIELD_SEP}%aI{_FIELD_SEP}%s"


@dataclass(frozen=True)
class Blocker:
    """一类拦截。kind: unpushed = 他人未推送提交;dirty = 脏树。

    detail 是人类可读的完整说明(拦截清单逐行指名)。
    """

    kind: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def _run(project_dir: Path, *args: str,
         timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=project_dir, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def _rev_parse(project_dir: Path, ref: str) -> str | None:
    """ref 完整 hash;无法解析(不存在/未出生)→ None。"""
    r = _run(project_dir, "rev-parse", "--verify", "--quiet", ref)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def _fetch_origin(project_dir: Path) -> bool:
    """fetch origin 最佳努力:无 origin 远端/失败/超时 → False(不阻断检查)。"""
    if _run(project_dir, "remote", "get-url", "origin").returncode != 0:
        return False
    try:
        r = _run(project_dir, "fetch", "--quiet", "origin",
                 timeout=_FETCH_TIMEOUT_S)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _unpushed_since_origin_main(
        project_dir: Path) -> list[tuple[str, str, str, str]] | None:
    """origin/main..HEAD 的提交元组 (hash, author, iso_time, subject)。

    origin/main 无法定位 → None(调用方按「无法校验 = 宁可误拦」处置)。
    """
    r = _run(project_dir, "log", f"--format={_LOG_FORMAT}", "origin/main..HEAD")
    if r.returncode != 0:
        return None
    commits: list[tuple[str, str, str, str]] = []
    for line in r.stdout.splitlines():
        parts = line.split(_FIELD_SEP)
        if len(parts) == 4:
            commits.append((parts[0], parts[1], parts[2], parts[3]))
    return commits


def _dirty_paths(project_dir: Path) -> list[str]:
    """工作区/索引脏文件(含未跟踪,rename 取新路径),排除编排器记号。"""
    r = _run(project_dir, "-c", "core.quotepath=false",
             "status", "--porcelain", "-uall")
    if r.returncode != 0:
        raise RuntimeError(f"git status 失败: {r.stderr.strip() or r.stdout.strip()}")
    paths: list[str] = []
    for line in r.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:                      # rename/拷贝:取新路径
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if path and path not in IGNORED_DIRTY_PATHS and path not in paths:
            paths.append(path)
    return paths


def check_pre_merge(project_dir: str | Path, *,
                    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES
                    ) -> list[Blocker]:
    """合 main 前置守卫:返回阻塞清单,空列表 = 可以合。

    规则(fetch 后):
      - origin/main 无法定位 → 拦(无法校验,宁可误拦);
      - `git log origin/main..HEAD` 非空且含非白名单前缀提交 → 拦(他人未推送);
      - 工作区/索引脏(排除 .orc-base)→ 拦。

    allowed_prefixes 可覆盖默认 loop 签名白名单(可配置,design Q2)。
    """
    project_dir = Path(project_dir)
    blockers: list[Blocker] = []
    _fetch_origin(project_dir)
    commits = _unpushed_since_origin_main(project_dir)
    if commits is None:
        blockers.append(Blocker(
            "unpushed",
            "无法定位 origin/main(未配置 origin 或从未 fetch),无法校验他人未推送"
            "提交——宁可误拦,请人工确认后再合 main"))
    else:
        others = [(h, a, t, s) for (h, a, t, s) in commits
                  if not any(s.startswith(p) for p in allowed_prefixes)]
        if others:
            lines = [f"  {h[:12]}  {a}  {t}  {s}" for h, a, t, s in others]
            blockers.append(Blocker(
                "unpushed",
                f"origin/main 之后存在 {len(others)} 个非 loop 签名提交"
                f"(他人未推送,重置同步会丢弃):\n" + "\n".join(lines)))
    dirty = _dirty_paths(project_dir)
    if dirty:
        blockers.append(Blocker(
            "dirty",
            "工作区/索引有未提交改动(同步 main 时会被丢弃,须先提交/还原): "
            + ", ".join(dirty)))
    return blockers


def make_loop_merge_fields(project_dir: str | Path) -> dict[str, str]:
    """合 main 成功后生成 loop_merge 审计事件字段 {base, head_before, head_after}。

    时序(dev-loop 快道):先 fetch 并把 main 同步到 origin/main,再合切片。故:
      base        = origin/main(合并基线);
      head_before = HEAD 与 origin/main 的 merge-base(同步后即合并前 main HEAD);
      head_after  = 合并后的 HEAD。
    调用方(dev-loop 合并点)补 ticket 字段、以 actor="loop" 写事件流:
      append_event(pool, ticket_id, "loop", "loop_merge", **make_loop_merge_fields(...))
    """
    project_dir = Path(project_dir)
    head_after = _rev_parse(project_dir, "HEAD") or ""
    base = _rev_parse(project_dir, "origin/main") or ""
    if base and head_after:
        r = _run(project_dir, "merge-base", base, "HEAD")
        head_before = r.stdout.strip() if r.returncode == 0 else base
    else:
        head_before = head_after
    return {"base": base, "head_before": head_before, "head_after": head_after}
