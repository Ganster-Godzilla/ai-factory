import pytest


@pytest.fixture
def pool(tmp_path):
    p = tmp_path / "pool"
    (p / "tickets").mkdir(parents=True)
    return p


@pytest.fixture(autouse=True)
def _bypass_gate_by_default(monkeypatch, request):
    """T-2026-0829-001 G4:既有用例主题是状态机/审批/运行器机制,不是门禁;
    默认把 transition 的产物门禁旁路保持单测聚焦。真闸门测试集中在
    test_gate_enforcement.py(该文件不旁路);test_gates.py 直接测 check_gate 不受影响。"""
    if request.node.path.name == "test_gate_enforcement.py":
        return
    from orchestrator.daemon import statemachine as sm
    monkeypatch.setattr(sm, "_enforce_gate", lambda *a, **k: None)
