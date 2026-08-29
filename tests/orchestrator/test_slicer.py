import pytest
from orchestrator.daemon.slicer import load_task_list, make_packet, ready_tasks, scope_violations
from orchestrator.daemon.ticket import new_ticket


def test_load_and_validate(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text(
        "- id: task-1\n  title: 建模型\n  acceptance_cmd: pytest -x\n  depends_on: []\n"
        "- id: task-2\n  title: 写接口\n  acceptance_cmd: pytest\n  depends_on: [task-1]\n",
        encoding="utf-8")
    tasks = load_task_list(f)
    assert [t["id"] for t in tasks] == ["task-1", "task-2"]
    assert tasks[0]["status"] == "pending"


def test_ready_respects_dependencies(tmp_path):
    tasks = [
        {"id": "task-1", "status": "pending", "depends_on": []},
        {"id": "task-2", "status": "pending", "depends_on": ["task-1"]},
    ]
    assert [t["id"] for t in ready_tasks(tasks)] == ["task-1"]
    tasks[0]["status"] = "done"
    assert [t["id"] for t in ready_tasks(tasks)] == ["task-2"]


def test_bad_dependency_rejected(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text("- id: task-1\n  title: x\n  acceptance_cmd: c\n  depends_on: [ghost]\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="ghost"):
        load_task_list(f)


def test_make_packet_has_tdd(pool, tmp_path):
    t = new_ticket(pool, project="p", summary="x")
    pkt = make_packet({"id": "task-1", "title": "建模型", "acceptance_cmd": "pytest -x",
                       "depends_on": []}, t, tmp_path, "设计节选")
    assert pkt.role == "dev"
    assert "TDD" in pkt.prompt and "pytest -x" in pkt.prompt
    assert pkt.workdir == tmp_path


def test_circular_dependency_rejected(tmp_path):
    f = tmp_path / "tasks.yaml"
    f.write_text(
        "- id: a\n  title: x\n  acceptance_cmd: c\n  depends_on: [b]\n"
        "- id: b\n  title: y\n  acceptance_cmd: c\n  depends_on: [a]\n",
        encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="循环依赖"):
        load_task_list(f)


def test_scope_field_passes_through_load(tmp_path):
    # R7:scope 是可选字段,装载原样保留;旧清单无该键也合法(缺省不检查)
    f = tmp_path / "tasks.yaml"
    f.write_text(
        "- id: task-1\n  title: 改代码\n  acceptance_cmd: pytest -x\n  depends_on: []\n"
        "  scope: ['orchestrator/**', 'tests/**']\n"
        "- id: task-2\n  title: 旧清单无 scope\n  acceptance_cmd: pytest\n  depends_on: []\n",
        encoding="utf-8")
    tasks = load_task_list(f)
    assert tasks[0]["scope"] == ["orchestrator/**", "tests/**"]
    assert "scope" not in tasks[1]


def test_scope_violations_matching():
    files = ["orchestrator/daemon/runner.py", "tests/test_x.py", "docs/a.md"]
    # fnmatch 语义:`*` 跨目录分隔符,`orchestrator/**` 命中深层路径
    assert scope_violations(files, ["orchestrator/**", "tests/**"]) == ["docs/a.md"]
    assert scope_violations(files, ["**/*"]) == []            # 全开工=显式放开,不算越界
    assert scope_violations(files, ["docs/*"]) == files[:2]   # 单层 glob 同样跨 /
    assert scope_violations(files, ["orchestrator/daemon/runner.py"]) == files[1:]
    assert scope_violations(files, []) == []                  # 缺省不检查
    assert scope_violations(files, None) == []
    assert scope_violations(files, "docs/*") == files[:2]     # 误写成单个字符串也容住


def test_make_packet_declares_scope(pool, tmp_path):
    # R7:dev 派单时就看到改动边界,而不是等越界判负才知道
    t = new_ticket(pool, project="p", summary="x")
    pkt = make_packet({"id": "task-1", "title": "建模型", "acceptance_cmd": "pytest -x",
                       "depends_on": [], "scope": ["orchestrator/**"]},
                      t, tmp_path, "节选")
    assert "orchestrator/**" in pkt.prompt
    assert "判负" in pkt.prompt
    pkt2 = make_packet({"id": "task-2", "title": "旧清单不带边界", "acceptance_cmd": "c",
                        "depends_on": []}, t, tmp_path, "节选")
    assert "scope" not in pkt2.prompt        # 旧清单 prompt 不变
