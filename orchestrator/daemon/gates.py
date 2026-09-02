"""阶段门禁(T-2026-0829-001 设计 M3):按 ARTIFACT_MANIFEST 逐件机器校验。

门禁分级(D4):本模块只管机器项(存在/非空/必含章节/必含内容/tasks 契约/留痕),
语义质量由 human_checklist 留给审批人。存量不追溯(D3):created_at 为空直接放行;
incident 事故单走快速通道,全礼仪豁免(评审 R3-6)。
"""
from __future__ import annotations

import re
from pathlib import Path

from orchestrator.daemon.artifacts import ARTIFACT_MANIFEST, manifest_for_edge
from orchestrator.daemon.doccheck import check as doccheck
from orchestrator.daemon.slicer import load_task_list


def _fail(path: str, reason: str) -> str:
    return f"FAIL: {path}: {reason}"


# T-2026-0902-015 S1:QA 结论判定词表(基于现有验收报告真实措辞采样)。
# fail 优先于 pass:"不通过"含"通过"子串,先判 fail 防误放(R6)。
_VERDICT_FAIL = ("不通过", "no-go")
_VERDICT_PASS = ("验收通过", "通过", "放行", "go")


def parse_verdict(text: str) -> str:
    """QA 验收报告"结论"章节正文 → "pass" | "fail" | "unknown"。

    fail 优先:任一 fail 词命中即 fail(即使同含 pass 词);否则命中 pass 词为
    pass;正文为空或两族都不命中 → unknown(调用方按 fail-closed 处理)。
    纯函数:不读文件、不碰 pool,大小写不敏感。
    """
    body = (text or "").lower()
    if not body.strip():
        return "unknown"
    if any(w in body for w in _VERDICT_FAIL):
        return "fail"
    if any(w in body for w in _VERDICT_PASS):
        return "pass"
    return "unknown"


def project_dir_for(cfg: dict, project: str) -> Path | None:
    """项目名 → cfg projects 登记目录(cli/dashboard 共置,评审 R3-10);
    未登记 → None(legacy 单不需要;新单会在 transition 报开发错误)。"""
    p = (cfg.get("projects") or {}).get(project)
    return Path(p) if p else None


def gate_required(ticket) -> bool:
    """新门禁生效边界(D3):created_at 为空=存量单,不追溯;
    incident 事故单豁免(快速通道,评审 R3-6:全礼仪卡死自动事故流)。"""
    return (getattr(ticket, "created_at", None) is not None
            and getattr(ticket, "type", "feature") != "incident")


def _resolve_rel(project_dir: Path, template: str, tid: str) -> str | None:
    """路径模板 → 实际相对路径(统一走 artifacts.resolve_artifact_path)。"""
    from orchestrator.daemon.artifacts import resolve_artifact_path
    return resolve_artifact_path(project_dir, template, tid)


def check_gate(project_dir: Path, ticket, to_state: str) -> list[str]:
    """迁移到 to_state 前的产物校验;返回 FAIL 行列表,空=放行。"""
    stage = manifest_for_edge(ticket.state, to_state)
    if stage is None or not gate_required(ticket):
        return []
    spec = ARTIFACT_MANIFEST[stage]
    fails: list[str] = []

    for art in spec["artifacts"]:
        rel = _resolve_rel(Path(project_dir), art["path"], ticket.id)
        if rel is None:
            fails.append(_fail(art["path"].replace("{tid_dir}",
                                                 f"{ticket.id}-<短名>"),
                               "产物不存在(工单文件夹未建)"))
            continue
        p = Path(project_dir) / rel
        if not p.is_file():
            fails.append(_fail(rel, "产物不存在"))
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:   # Windows 文件锁/权限:IO 异常也归一为 FAIL(评审 R3-4)
            fails.append(_fail(rel, f"读取失败: {e}"))
            continue
        if not text.strip():
            fails.append(_fail(rel, "产物为空"))   # 空 tasks.yaml 同样拦(评审 R3-1)
            continue
        if art.get("tasks_contract"):
            try:
                tasks = load_task_list(p)
            except Exception as e:  # noqa: BLE001 — 契约违规转 FAIL 行
                msg = re.sub(r"\s+", " ", str(e))   # 单行化:多行错误破坏 FAIL 行协议
                fails.append(_fail(rel, f"tasks 契约校验失败: {msg}"))
                continue
            if not tasks:
                fails.append(_fail(rel, "任务清单为空(零任务不许过 P2)"))
            continue
        for reason in doccheck(text, art["require_sections"],
                               require_content=art["require_content"]):
            fails.append(_fail(rel, reason))

    if spec.get("task_verify_required"):
        for task in ticket.tasks or []:
            if task.get("status") != "done":
                fails.append(_fail(f"task[{task.get('id')}]", "任务未完成"))
            elif task.get("acceptance_cmd") and task.get("verify") != "passed":
                fails.append(_fail(f"task[{task.get('id')}]",
                                   "verify 留痕非 passed"
                                   "(补救:核实后手改 yaml 或 closed 重开)"))

    # T-2026-0902-015 S2:P4 边(p4_verifying→p5_ready)追加 verdict 检查——
    # QA 报告"结论"非通过(fail/unknown)即挂起退回,fail-closed。
    # 报告缺失/无"结论"章节时,上方产物门禁已 FAIL(不重复判 verdict)。
    if stage == "P4" and not any("验收报告" in f for f in fails):
        report_rel = _resolve_rel(
            Path(project_dir),
            "document/business/{tid_dir}/04_测试/验收报告.md", ticket.id)
        if report_rel is not None:
            rpt = Path(project_dir) / report_rel
            if rpt.is_file():
                verdict = parse_verdict(_section_text(
                    rpt.read_text(encoding="utf-8", errors="replace"), "结论"))
                if verdict != "pass":
                    fails.append(_fail(
                        report_rel,
                        f"QA 结论非通过(verdict={verdict}): 挂起退回"
                        "(R11:状态机须读结论,不只认退出码)"))
    return fails


def _section_text(text: str, section: str) -> str:
    """取 `## <section>` 至下一 `## `(或文末)的正文;无该章节 → 空串。"""
    m = re.search(rf"^##\s+{re.escape(section)}\s*$", text, flags=re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, flags=re.M)
    return rest[:nxt.start()] if nxt else rest
