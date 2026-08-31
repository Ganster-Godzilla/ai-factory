"""任务切片:P2 设计产物 → 可派发的任务包。"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import yaml

from orchestrator.adapters.base import TaskPacket

TDD_INSTRUCTION = (
    "严格遵守 TDD:先写一个失败的测试,再写最小实现让它通过,"
    "然后运行验收命令 `{cmd}` 直至退出码为 0。不许先写实现。"
)


def load_task_list(path: Path) -> list[dict]:
    tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("任务 id 重复")
    for t in tasks:
        t.setdefault("status", "pending")
        t.setdefault("attempts", 0)
        for dep in t.get("depends_on", []):
            if dep not in ids:
                raise ValueError(f"未知依赖: {dep}")
    # 循环依赖检测(DFS 三色标记)
    by_id = {t["id"]: t for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in by_id}

    def visit(i, stack):
        color[i] = GRAY
        for dep in by_id[i].get("depends_on", []):
            if dep not in by_id:
                continue
            if color[dep] == GRAY:
                raise ValueError(f"循环依赖: {' -> '.join(stack + [i, dep])}")
            if color[dep] == WHITE:
                visit(dep, stack + [i])
        color[i] = BLACK

    for i in by_id:
        if color[i] == WHITE:
            visit(i, [])
    return tasks


def ready_tasks(tasks: list[dict]) -> list[dict]:
    done = {t["id"] for t in tasks if t["status"] == "done"}
    return [t for t in tasks
            if t["status"] == "pending" and set(t.get("depends_on", [])) <= done]


def scope_violations(files: list[str], scope: list[str] | str | None) -> list[str]:
    """R7:改动文件越出 scope 的清单。fnmatch 语义(相对项目根,`**` 递归——
    fnmatch 的 `*` 本就跨目录分隔符,故 `orchestrator/**` 可命中深层路径)。
    scope 缺省/为空 → 不检查,返回空(兼容旧清单);误写成单个字符串也容住。"""
    if isinstance(scope, str):
        scope = [scope]
    patterns = [str(p) for p in (scope or []) if p]
    if not patterns:
        return []
    return [f for f in files
            if not any(fnmatch(f, p) for p in patterns)]


def make_packet(task: dict, ticket, workdir: Path, design_excerpt: str,
                model: str | None = None) -> TaskPacket:
    prompt = (
        f"你是开发角色,在 git worktree 中独立完成任务 {task['id']}: {task['title']}\n"
        f"工单: {ticket.id} — {ticket.summary}\n"
        f"设计节选:\n{design_excerpt}\n\n"
        + TDD_INSTRUCTION.format(cmd=task["acceptance_cmd"])
    )
    if task.get("scope"):
        # R7:dev 先知道改动边界,而不是等越界判负才看到(越界即视同验收失败)
        prompt += (
            f"\n改动边界(scope,只许动这些,越出即判负): {', '.join(task['scope'])}"
        )
    return TaskPacket(role="dev", prompt=prompt, workdir=workdir,
                      acceptance_cmd=task["acceptance_cmd"], budget=ticket.budget,
                      model=model,
                      # task.timeout 分级(G8 决议的接线缺口,003-S8 实证):
                      # 前端等大切片 1800s 不够,任务可显式声明,上限 7200
                      timeout=min(int(task.get("timeout", 1800)), 7200))
