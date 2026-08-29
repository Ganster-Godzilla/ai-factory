"""Harness 适配器注册表:按名取实例。"""
from orchestrator.adapters.base import HarnessAdapter
from orchestrator.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.adapters.dsh import DshAdapter
from orchestrator.adapters.fake import FakeHarness

_REGISTRY = {
    "claude_code": ClaudeCodeAdapter,
    "dsh": DshAdapter,
    "fake": FakeHarness,
}


def get_adapter(name: str, keys_dir=None, est_call_cny: float = 0.0) -> HarnessAdapter:
    if name == "dsh":
        # est_call_cny:明放估算单价(T-2026-0829-004),由 cli 从 cfg budgets 透传
        return DshAdapter(keys_dir=keys_dir, est_call_cny=est_call_cny)
    return _REGISTRY[name]()
