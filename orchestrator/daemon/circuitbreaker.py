"""任务级熔断阶梯:重试(≤3)→ 架构师会诊(≤1)→ 挂起。spec §5.2。"""
from __future__ import annotations

from pathlib import Path

from orchestrator.adapters.base import TaskPacket

MAX_RETRY = 3


def next_action(task: dict) -> str:
    if task["attempts"] < MAX_RETRY:
        return "retry"
    if not task.get("consulted"):
        return "consult"
    return "suspend"


def retry_prompt(task: dict, base_prompt: str, last_output: str) -> str:
    return (
        f"{base_prompt}\n\n第 {task['attempts'] + 1} 次尝试。上次错误:\n"
        f"{last_output[:800]}\n先分析失败原因再动手。"
    )


def consult_packet(task: dict, ticket, last_output: str, workdir: Path) -> TaskPacket:
    prompt = (
        f"你是架构师,受邀会诊一个失败任务。\n"
        f"工单: {ticket.id} — {ticket.summary}\n"
        f"任务: {task['id']}: {task['title']}(已失败 {task['attempts']} 次)\n"
        f"错误输出:\n{last_output[:1500]}\n\n"
        f"给出诊断与修复建议(不写代码)。输出格式:根因 / 修复方案 / 是否需要改设计。"
    )
    return TaskPacket(role="architect", prompt=prompt, workdir=workdir,
                    budget=ticket.budget)
