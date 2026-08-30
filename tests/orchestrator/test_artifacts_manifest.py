"""G1:ARTIFACT_MANIFEST 单一事实源(T-2026-0829-001 设计 M1/D1)。"""
from orchestrator.daemon.artifacts import ARTIFACT_MANIFEST, manifest_for_edge

STAGES = ["P0", "P1", "P2", "P3", "P4", "P5_RELEASE", "P5_MONITOR"]


def test_manifest_covers_all_stages():
    assert list(ARTIFACT_MANIFEST.keys()) == STAGES


def test_gate_edges_match_statemachine():
    edges = {s["gate_edge"] for s in ARTIFACT_MANIFEST.values()}
    assert edges == {
        ("p0_proposed", "p1_drafting"),
        ("p1_drafting", "p1_proposed"),
        ("p2_designing", "p2_approved"),
        ("p3_running", "p4_verifying"),
        ("p4_verifying", "p5_ready"),
        ("p5_releasing", "monitoring"),
        ("monitoring", "done"),
    }


def test_manifest_for_edge_reverse_lookup():
    assert manifest_for_edge("p0_proposed", "p1_drafting") == "P0"
    assert manifest_for_edge("monitoring", "done") == "P5_MONITOR"
    assert manifest_for_edge("draft", "p0_proposed") is None   # 提交边非门禁(挂审批边界)
    assert manifest_for_edge("p1_drafting", "p1_proposed") == "P1"


def test_p0_proposal_artifact():
    arts = ARTIFACT_MANIFEST["P0"]["artifacts"]
    assert len(arts) == 1
    a = arts[0]
    assert a["path"] == "document/business/{tid_dir}/00_提案/提案.md"
    assert a["role"] == "pm"
    assert set(a["require_sections"]) == {"问题", "方向", "范围", "不做"}
    assert ARTIFACT_MANIFEST["P0"]["human_checklist"]


def test_p1_three_artifacts():
    paths = [a["path"] for a in ARTIFACT_MANIFEST["P1"]["artifacts"]]
    assert paths == ["document/business/{tid_dir}/01_需求分析/prd.md",
                     "document/business/{tid_dir}/01_需求分析/功能清单.md",
                     "document/business/{tid_dir}/01_需求分析/歧义澄清记录.md"]
    prd = next(a for a in ARTIFACT_MANIFEST["P1"]["artifacts"]
               if a["path"].endswith("prd.md"))
    assert set(prd["require_sections"]) == {"Why", "What", "验收标准"}
    cl = next(a for a in ARTIFACT_MANIFEST["P1"]["artifacts"]
              if "功能清单" in a["path"])
    assert "优先级" in cl["require_content"]


def test_p2_design_and_tasks_contract():
    paths = [a["path"] for a in ARTIFACT_MANIFEST["P2"]["artifacts"]]
    assert "document/business/{tid_dir}/02_设计文档/design.md" in paths
    assert "document/business/{tid_dir}/02_设计文档/tasks.yaml" in paths
    design = next(a for a in ARTIFACT_MANIFEST["P2"]["artifacts"]
                  if "design.md" in a["path"])
    assert set(design["require_sections"]) == {"Architecture", "How",
                                               "Checkpoints", "Rollback"}
    tasks = next(a for a in ARTIFACT_MANIFEST["P2"]["artifacts"]
                 if "tasks.yaml" in a["path"])
    assert tasks.get("tasks_contract") is True   # 必过 slicer 契约校验(D-清单)


def test_p3_verify_required_flag():
    p3 = ARTIFACT_MANIFEST["P3"]
    assert p3["artifacts"] == []
    assert p3["task_verify_required"] is True


def test_p4_p5_artifacts():
    p4 = ARTIFACT_MANIFEST["P4"]["artifacts"][0]
    assert p4["path"] == "document/business/{tid_dir}/04_测试/验收报告.md"
    assert set(p4["require_sections"]) == {"环境", "范围", "用例结果", "结论"}
    rel = ARTIFACT_MANIFEST["P5_RELEASE"]["artifacts"][0]
    assert set(rel["require_sections"]) == {"合并清单", "版本", "回滚方案"}
    mon = ARTIFACT_MANIFEST["P5_MONITOR"]["artifacts"][0]
    assert set(mon["require_sections"]) == {"观察窗", "健康检查", "结论"}
