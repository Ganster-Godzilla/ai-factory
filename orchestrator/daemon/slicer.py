"""任务切片:P2 设计产物 → 可派发的任务包。"""
from __future__ import annotations

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
    return tasks


def ready_tasks(tasks: list[dict]) -> list[dict]:
    done = {t["id"] for t in tasks if t["status"] == "done"}
    return [t for t in tasks
            if t["status"] == "pending" and set(t.get("depends_on", [])) <= done]


def make_packet(task: dict, ticket, workdir: Path, design_excerpt: str) -> TaskPacket:
    prompt = (
        f"你是开发角色,在 git worktree 中独立完成任务 {task['id']}: {task['title']}\n"
        f"工单: {ticket.id} — {ticket.summary}\n"
        f"设计节选:\n{design_excerpt}\n\n"
        + TDD_INSTRUCTION.format(cmd=task["acceptance_cmd"])
    )
    return TaskPacket(role="dev", prompt=prompt, workdir=workdir,
                      acceptance_cmd=task["acceptance_cmd"], budget=ticket.budget)
