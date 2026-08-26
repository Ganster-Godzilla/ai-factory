import pytest
from orchestrator.daemon.slicer import load_task_list, make_packet, ready_tasks
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
