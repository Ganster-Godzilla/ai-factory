"""阶段产物清单单一事实源(T-2026-0829-001 设计 D1)。

一切产物口径以本模块为权威:角色提示词、gates.py 闸门、口径文档
(docs/specs/T-2026-0829-001-artifact-standard.md)均引用/对齐本表,禁各自维护副本。
"""
from __future__ import annotations

ARTIFACT_MANIFEST: dict[str, dict] = {
    "P0": {
        # 门禁挂审批边界(p0_proposed→p1_drafting)而非提交边(draft→p0_proposed):
        # 提交时产物由提交人负责,审批时 boss 必须见到提案文档才放行(评审 R3 裁决——
        # 挂提交边会让探针采纳/cli 提交永远 409,draft 态无角色能产出提案)
        "gate_edge": ("p0_proposed", "p1_drafting"),
        "artifacts": [{
            "path": "document/business/{tid}-提案.md",
            "role": "pm",
            "require_sections": ["问题", "方向", "范围", "不做"],
            "require_content": [],
        }],
        "human_checklist": ["方向与范围是否成立"],
    },
    "P1": {
        "gate_edge": ("p1_drafting", "p1_proposed"),
        "artifacts": [
            {"path": "document/business/{tid}-prd.md",
             "role": "pm",
             "require_sections": ["Why", "What", "验收标准"],
             "require_content": []},
            {"path": "document/business/{tid}-功能清单.md",
             "role": "pm",
             "require_sections": ["功能清单"],
             "require_content": ["优先级"]},
            {"path": "document/business/{tid}-歧义澄清记录.md",
             "role": "pm",
             "require_sections": [],
             "require_content": []},   # 无歧义也须显式写"无歧义"(人工项)
        ],
        "human_checklist": ["Why 是否成立、验收标准可判定", "优先级合理"],
    },
    "P2": {
        "gate_edge": ("p2_designing", "p2_approved"),
        "artifacts": [
            {"path": "docs/specs/{tid}-design.md",
             "role": "architect",
             "require_sections": ["Architecture", "How", "Checkpoints", "Rollback"],
             "require_content": []},
            {"path": "docs/specs/{tid}-tasks.yaml",
             "role": "architect",
             "require_sections": [],
             "require_content": [],
             "tasks_contract": True},   # 必过 slicer.load_task_list 契约校验
        ],
        "human_checklist": ["方案合理、无未决开放问题", "切片粒度合理"],
    },
    "P3": {
        "gate_edge": ("p3_running", "p4_verifying"),
        "artifacts": [],   # 无文件产物:查工单 yaml task["verify"] 留痕
        "task_verify_required": True,
        "human_checklist": [],
    },
    "P4": {
        "gate_edge": ("p4_verifying", "p5_ready"),
        "artifacts": [{
            "path": "docs/specs/{tid}-验收报告.md",
            "role": "qa",
            "require_sections": ["环境", "范围", "用例结果", "结论"],
            "require_content": [],
        }],
        "human_checklist": ["缺陷处置结论可信"],
    },
    "P5_RELEASE": {
        "gate_edge": ("p5_releasing", "monitoring"),
        "artifacts": [{
            "path": "docs/specs/{tid}-发布记录.md",
            "role": "release",
            "require_sections": ["合并清单", "版本", "回滚方案"],
            "require_content": [],
        }],
        "human_checklist": ["回滚方案可执行"],
    },
    "P5_MONITOR": {
        "gate_edge": ("monitoring", "done"),
        "artifacts": [{
            "path": "docs/specs/{tid}-观察窗报告.md",
            "role": "sre",
            "require_sections": ["观察窗", "健康检查", "结论"],
            "require_content": [],
        }],
        "human_checklist": ["观察时长达标(默认 24h;orchestrator.yaml "
                            "monitoring.window_hours 预留未接线,暂不可配)"],
    },
}


def manifest_for_edge(frm: str, to: str) -> str | None:
    """门禁边反查阶段标识;非门禁边 → None。"""
    for stage, spec in ARTIFACT_MANIFEST.items():
        if spec["gate_edge"] == (frm, to):
            return stage
    return None
