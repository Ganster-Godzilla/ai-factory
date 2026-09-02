"""G3:gates.check_gate 闸门(T-2026-0829-001 设计 M3)。"""
from datetime import datetime

from orchestrator.daemon.gates import check_gate
from orchestrator.daemon.ticket import Ticket, new_ticket, save_ticket


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
    _write(tmp_path, f"document/business/{t.id}-测试需求/00_提案/提案.md", "")
    t.state = "p0_proposed"
    fails = check_gate(tmp_path, t, "p1_drafting")
    assert any("空" in f for f in fails)


def test_gate_missing_sections_and_content(pool, tmp_path):
    t = _new(pool)
    _write(tmp_path, f"document/business/{t.id}-测试需求/00_提案/提案.md", "# 只有问题\n")
    t.state = "p0_proposed"
    fails = check_gate(tmp_path, t, "p1_drafting")
    assert any('缺少章节 "方向"' in f for f in fails)
    assert any('缺少章节 "不做"' in f for f in fails)


def test_gate_complete_p0_passes(pool, tmp_path):
    t = _new(pool)
    _write(tmp_path, f"document/business/{t.id}-测试需求/00_提案/提案.md",
           "# 提案\n## 问题\nx\n## 方向\nx\n## 范围\nx\n## 不做\nx\n")
    assert check_gate(tmp_path, t, "p1_drafting") == []


def test_gate_p1_requires_content_keyword(pool, tmp_path):
    t = _new(pool)
    t.state = "p1_drafting"
    _write(tmp_path, f"document/business/{t.id}-测试需求/01_需求分析/prd.md",
           "# PRD\n## Why\nx\n## What\nx\n## 验收标准\nx\n")
    _write(tmp_path, f"document/business/{t.id}-测试需求/01_需求分析/功能清单.md",
           "# 功能清单\n只有功能没有等级列\n")
    _write(tmp_path, f"document/business/{t.id}-测试需求/01_需求分析/歧义澄清记录.md", "# 无歧义\n")
    fails = check_gate(tmp_path, t, "p1_proposed")
    assert any('缺少内容 "优先级"' in f for f in fails)


def test_gate_tasks_yaml_contract(pool, tmp_path):
    t = _new(pool)
    t.state = "p2_designing"
    _write(tmp_path, f"document/business/{t.id}-测试需求/02_设计文档/design.md",
           "# D\n## Architecture\nx\n## How\nx\n## Checkpoints\nx\n## Rollback\nx\n")
    _write(tmp_path, f"document/business/{t.id}-测试需求/02_设计文档/tasks.yaml",
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
    _write(tmp_path, f"document/business/{t.id}-测试需求/02_设计文档/design.md",
           "# D\n## Architecture\nx\n## How\nx\n## Checkpoints\nx\n## Rollback\nx\n")
    _write(tmp_path, f"document/business/{t.id}-测试需求/02_设计文档/tasks.yaml", "")
    fails = check_gate(tmp_path, t, "p2_approved")
    assert any("tasks.yaml" in f and "空" in f for f in fails)
    _write(tmp_path, f"document/business/{t.id}-测试需求/02_设计文档/tasks.yaml", "# 只有注释\n")
    fails = check_gate(tmp_path, t, "p2_approved")
    assert any("空" in f for f in fails)


def test_incident_bypasses_gate(pool, tmp_path):
    # 评审 R3-6:incident 事故单快速通道,全礼仪豁免
    t = _new(pool)
    t.type = "incident"
    t.state = "p1_drafting"
    assert check_gate(tmp_path, t, "p1_proposed") == []


def test_biz_dir_glob_resolution(pool, tmp_path):
    # T-2026-0830-001 F2:{tid_dir} glob 前缀解析,短名任意;多匹配取字典序首
    from orchestrator.daemon.gates import _resolve_rel
    (tmp_path / "document/business/T-1-zeta/00_提案").mkdir(parents=True)
    (tmp_path / "document/business/T-1-alpha/00_提案").mkdir(parents=True)
    got = _resolve_rel(tmp_path, "document/business/{tid_dir}/00_提案/提案.md", "T-1")
    assert got == "document/business/T-1-alpha/00_提案/提案.md"
    assert _resolve_rel(tmp_path, "docs/specs/{tid}-design.md", "T-1") == \
        "docs/specs/T-1-design.md"
    assert _resolve_rel(tmp_path,
                        "document/business/{tid_dir}/00_提案/提案.md", "T-9") is None


# --- T-2026-0902-015 S1:parse_verdict 纯函数(fail 优先/pass 族/unknown) ---
from orchestrator.daemon.gates import parse_verdict


def test_parse_verdict_fail_plain():
    assert parse_verdict("不通过,P4 挂起,退回处置。") == "fail"


def test_parse_verdict_pass_simple():
    assert parse_verdict("通过") == "pass"
    assert parse_verdict("验收通过。遗留(sk T-005)已登记 backlog,不阻塞。") == "pass"


def test_parse_verdict_pass_bold_with_count():
    assert parse_verdict("**通过(8/8 验收命令全绿 + check-pool-load 0 bad)。**") == "pass"


def test_parse_verdict_pass_release_wording():
    assert parse_verdict("方案 B 全部验收用例通过,建议放行进入发布/观察窗。") == "pass"


def test_parse_verdict_unknown_empty_and_vague():
    assert parse_verdict("") == "unknown"
    assert parse_verdict("见上文。") == "unknown"


def test_parse_verdict_fail_wins_over_pass_substring():
    # R6:"不通过"含"通过"子串,fail 必须优先,防误放
    assert parse_verdict("不通过……后续可转通过") == "fail"


def test_parse_verdict_nogo_is_fail():
    assert parse_verdict("NO-GO:阻塞项未清") == "fail"
    assert parse_verdict("no-go") == "fail"


# --- T-2026-0902-015 S3:P4 放行留痕 verdict=pass 事件 ---
def test_p4_release_writes_verdict_pass_event(pool, tmp_path):
    import subprocess
    from orchestrator.adapters.fake import FakeHarness
    from orchestrator.daemon.events import read_events
    from orchestrator.daemon.runner import advance_once

    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=proj, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    (proj / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=proj, check=True,
                   capture_output=True)

    t = _new(pool)
    t.state = "p4_verifying"
    save_ticket(pool, t)
    rep = proj / f"document/business/{t.id}-测试/04_测试/验收报告.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("# 验收报告\n## 环境\nx\n## 范围\nx\n## 用例结果\nx\n"
                   "## 结论\n**通过。**\n", encoding="utf-8")

    advance_once(pool, t.id, FakeHarness(), proj,
                 cfg={"budgets": {"k3_week_token_budget": 10**9,
                                  "ds_daily_cny": 10**9}})
    from orchestrator.daemon.ticket import load_ticket
    assert load_ticket(pool, t.id).state == "p5_ready"
    evs = [e for e in read_events(pool, t.id) if e["event"] == "verdict"]
    assert evs and evs[-1]["verdict"] == "pass"


def test_parse_verdict_pass_with_parenthetical_bu_tongguo():
    # R6 反例(015 自验发现):主判定"通过"在句首,括号里"不通过"是提及非判定 → pass
    assert parse_verdict(
        "**通过。** 三条切片全绿,fail-closed 语义(不通过/缺章节/无法解析一律挂起)"
        "实证成立。") == "pass"


def test_parse_verdict_fail_when_bu_tongguo_leads():
    # "不通过"在判定位(句首)→ fail,即便后文有"通过"字样
    assert parse_verdict("**不通过,P4 挂起。** 修复后可转通过。") == "fail"


def test_parse_verdict_earliest_keyword_wins():
    # 判定词取最靠前者:放行在前的 pass;不通过在前的 fail
    assert parse_verdict("放行进入观察窗;此前不通过项已清。") == "pass"
    assert parse_verdict("不通过;放行暂缓。") == "fail"


def test_parse_verdict_go_word_boundary():
    # 英文 go 须词边界:"GO" 独立为 pass;含 go 子串的词(good/google/ongoing)不算
    assert parse_verdict("GO") == "pass"
    assert parse_verdict("结论:GO,可发布。") == "pass"
    assert parse_verdict("no-go,阻塞未清") == "fail"
    # 不含判定词,仅含 go 子串 → unknown(不误判 pass)
    assert parse_verdict("ongoing investigation, good progress") == "unknown"
    assert parse_verdict("结果尚可,google 一下便知") == "unknown"
