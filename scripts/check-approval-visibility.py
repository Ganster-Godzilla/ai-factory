#!/usr/bin/env python3
"""check-approval-visibility.py — R16 E2:待批工单必须在审批中心可见。

两查:
1. 待批状态工单(p0_proposed/p1_proposed/p5_ready)必须落在审批桶
   (views.pending_groups 预演;桶口径漂移即 FAIL);
2. p2_designing 且设计两件套(02_设计文档/design.md+tasks.yaml)已齐
   → owner_role 必须已交还 boss 且工单出现在 P2 桶。
   防"设计做完但没交还 owner,审批中心无单可批"
   (2026-09-08 T-2026-0908-002 事故,boss 第 2 次遇到)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.dashboard import views  # noqa: E402

_PENDING_STATES = ("p0_proposed", "p1_proposed", "p5_ready")


def _project_dirs() -> dict[str, Path]:
    cfg = yaml.safe_load((ROOT / "orchestrator.yaml").read_text(encoding="utf-8")) or {}
    out: dict[str, Path] = {}
    for name, raw in (cfg.get("projects") or {}).items():
        text = str(raw or "").strip()
        if text:
            out[str(name)] = Path(text)
    return out


def _design_ready(project_dir: Path, ticket_id: str) -> bool:
    base = project_dir / "document" / "business"
    for match in sorted(base.glob(f"{ticket_id}-*/02_设计文档")):
        if (match / "design.md").exists() and (match / "tasks.yaml").exists():
            return True
    return False


def main() -> int:
    pool = ROOT / "pool"
    groups = views.pending_groups(pool)
    in_bucket = {t.id for rows in groups.values() for t in rows}
    proj_dirs = _project_dirs()
    fails: list[str] = []
    for t in views._all_tickets(pool):
        if t.state in _PENDING_STATES and t.id not in in_bucket:
            fails.append(
                f"{t.id}: 待批状态 {t.state} 但未出现在审批桶(桶口径漂移?)"
            )
        if t.state == "p2_designing":
            pdir = proj_dirs.get(str(t.project))
            if pdir and _design_ready(pdir, t.id) and (
                t.owner_role != "boss" or t.id not in in_bucket
            ):
                fails.append(
                    f"{t.id}: 设计两件套已齐但 owner_role={t.owner_role!r} "
                    "→ 审批中心 P2 桶不可见,boss 无单可批;"
                    "请 owner_role 交还 boss 并补 note 事件"
                )
    if fails:
        print("APPROVAL-VISIBILITY FAIL")
        for line in fails:
            print(" -", line)
        return 1
    print("APPROVAL-VISIBILITY OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
