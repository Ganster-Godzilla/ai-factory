"""阶段门禁(T-2026-0829-001 设计 M3):按 ARTIFACT_MANIFEST 逐件机器校验。

门禁分级(D4):本模块只管机器项(存在/非空/必含章节/必含内容/tasks 契约/留痕),
语义质量由 human_checklist 留给审批人。存量不追溯(D3):created_at 为空直接放行。
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.daemon.artifacts import manifest_for_edge
from orchestrator.daemon.doccheck import check as doccheck
from orchestrator.daemon.slicer import load_task_list


def _fail(path: str, reason: str) -> str:
    return f"FAIL: {path}: {reason}"


def gate_required(ticket) -> bool:
    """新门禁生效边界(D3):created_at 为空=存量单,不追溯。"""
    return getattr(ticket, "created_at", None) is not None


def check_gate(project_dir: Path, ticket, to_state: str) -> list[str]:
    """迁移到 to_state 前的产物校验;返回 FAIL 行列表,空=放行。"""
    stage = manifest_for_edge(ticket.state, to_state)
    if stage is None:
        return []
    if not gate_required(ticket):
        return []   # 存量单不追溯(D3)
    from orchestrator.daemon.artifacts import ARTIFACT_MANIFEST
    spec = ARTIFACT_MANIFEST[stage]
    fails: list[str] = []

    for art in spec["artifacts"]:
        rel = art["path"].format(tid=ticket.id)
        p = Path(project_dir) / rel
        if not p.is_file():
            fails.append(_fail(rel, "产物不存在"))
            continue
        if art.get("tasks_contract"):
            try:
                load_task_list(p)
            except Exception as e:  # noqa: BLE001 — 契约违规转 FAIL 行
                fails.append(_fail(rel, f"tasks 契约校验失败: {e}"))
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            fails.append(_fail(rel, "产物为空"))
            continue
        for line in doccheck(text, art["require_sections"],
                             require_content=art["require_content"]):
            fails.append(_fail(rel, line.replace("FAIL: ", "")))

    if spec.get("task_verify_required"):
        for task in ticket.tasks or []:
            if task.get("status") != "done":
                fails.append(_fail(f"task[{task.get('id')}]", "任务未完成"))
            elif task.get("acceptance_cmd") and task.get("verify") != "passed":
                fails.append(_fail(f"task[{task.get('id')}]",
                                   "verify 留痕非 passed"))
    return fails
