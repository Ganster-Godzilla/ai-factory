"""G3:gates.check_gate 闸门(T-2026-0829-001 设计 M3)。"""
from datetime import datetime

from orchestrator.daemon.gates import check_gate
from orchestrator.daemon.ticket import Ticket, new_ticket


def _new(pool, summary="闸门测试"):
    return new_ticket(pool, project="p", summary=summary)


def _legacy(pool):
    """存量单:created_at=None(旧 yaml 无字段)。"""
    t = _new(pool, "存量单")
    t.created_at = None
    return t


def _write(project_dir, rel, text="# 标题\n内容\n"):
    p = project_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_new_ticket_writes_created_at_utc(pool):
    t = _new(pool)
    assert t.created_at is not None
    datetime.fromisoformat(t.created_at)   # ISO 可解析


def test_legacy_ticket_loads_created_at_none(tmp_path):
    p = tmp_path / "T-2026-0101-001.yaml"
    p.write_text("id: T-2026-0101-001\ntype: feature\nproject: x\n"
                 "state: draft\nowner_role: pm\n", encoding="utf-8")
    assert Ticket.load(p).created_at is None


def test_gate_missing_artifact_fails(pool, tmp_path):
    t = _new(pool)
    t.state = "p0_proposed"
    fails = check_gate(tmp_path, t, "p1_drafting")
    assert any("提案.md" in f and "不存在" in f for f in fails)


def test_gate_empty_file_fails(pool, tmp_path):
    t = _new(pool)
    _write(tmp_path, f"document/business/{t.id}-提案.md", "")
    t.state = "p0_proposed"
    fails = check_gate(tmp_path, t, "p1_drafting")
    assert any("空" in f for f in fails)


def test_gate_missing_sections_and_content(pool, tmp_path):
    t = _new(pool)
    _write(tmp_path, f"document/business/{t.id}-提案.md", "# 只有问题\n")
    t.state = "p0_proposed"
    fails = check_gate(tmp_path, t, "p1_drafting")
    assert any('缺少章节 "方向"' in f for f in fails)
    assert any('缺少章节 "不做"' in f for f in fails)


def test_gate_complete_p0_passes(pool, tmp_path):
    t = _new(pool)
    _write(tmp_path, f"document/business/{t.id}-提案.md",
           "# 提案\n## 问题\nx\n## 方向\nx\n## 范围\nx\n## 不做\nx\n")
    assert check_gate(tmp_path, t, "p1_drafting") == []


def test_gate_p1_requires_content_keyword(pool, tmp_path):
    t = _new(pool)
    t.state = "p1_drafting"
    _write(tmp_path, f"document/business/{t.id}-prd.md",
           "# PRD\n## Why\nx\n## What\nx\n## 验收标准\nx\n")
    _write(tmp_path, f"document/business/{t.id}-功能清单.md",
           "# 功能清单\n只有功能没有等级列\n")
    _write(tmp_path, f"document/business/{t.id}-歧义澄清记录.md", "# 无歧义\n")
    fails = check_gate(tmp_path, t, "p1_proposed")
    assert any('缺少内容 "优先级"' in f for f in fails)


def test_gate_tasks_yaml_contract(pool, tmp_path):
    t = _new(pool)
    t.state = "p2_designing"
    _write(tmp_path, f"docs/specs/{t.id}-design.md",
           "# D\n## Architecture\nx\n## How\nx\n## Checkpoints\nx\n## Rollback\nx\n")
    _write(tmp_path, f"docs/specs/{t.id}-tasks.yaml",
           "- id: G1\n  depends_on: [G9]\n")   # 未知依赖
    fails = check_gate(tmp_path, t, "p2_approved")
    assert any("tasks.yaml" in f and "依赖" in f for f in fails)


def test_gate_p3_verify_required(pool, tmp_path):
    t = _new(pool)
    t.state = "p3_running"
    t.tasks = [{"id": "g1", "status": "done", "acceptance_cmd": "x",
                "verify": "failed"}]
    fails = check_gate(tmp_path, t, "p4_verifying")
    assert any("verify" in f for f in fails)
    t.tasks[0]["verify"] = "passed"
    assert check_gate(tmp_path, t, "p4_verifying") == []


def test_gate_p3_undone_task_fails(pool, tmp_path):
    t = _new(pool)
    t.state = "p3_running"
    t.tasks = [{"id": "g1", "status": "pending", "acceptance_cmd": None}]
    fails = check_gate(tmp_path, t, "p4_verifying")
    assert any("未完成" in f or "pending" in f for f in fails)


def test_legacy_ticket_bypasses_gate(pool, tmp_path):
    t = _legacy(pool)   # created_at=None:存量不追溯(设计 D3/AC-5)
    assert check_gate(tmp_path, t, "p1_drafting") == []


def test_non_gated_edge_no_check(pool, tmp_path):
    t = _new(pool)
    assert check_gate(tmp_path, t, "p1_drafting") == []   # 非门禁边直接放行


def test_empty_tasks_yaml_fails(pool, tmp_path):
    # 评审 R3-1:空 tasks.yaml 不许滑过 P2(曾 continue 跳过空文件检查)
    t = _new(pool)
    t.state = "p2_designing"
    _write(tmp_path, f"docs/specs/{t.id}-design.md",
           "# D\n## Architecture\nx\n## How\nx\n## Checkpoints\nx\n## Rollback\nx\n")
    _write(tmp_path, f"docs/specs/{t.id}-tasks.yaml", "")
    fails = check_gate(tmp_path, t, "p2_approved")
    assert any("tasks.yaml" in f and "空" in f for f in fails)
    _write(tmp_path, f"docs/specs/{t.id}-tasks.yaml", "# 只有注释\n")
    fails = check_gate(tmp_path, t, "p2_approved")
    assert any("空" in f for f in fails)


def test_incident_bypasses_gate(pool, tmp_path):
    # 评审 R3-6:incident 事故单快速通道,全礼仪豁免
    t = _new(pool)
    t.type = "incident"
    t.state = "p1_drafting"
    assert check_gate(tmp_path, t, "p1_proposed") == []
