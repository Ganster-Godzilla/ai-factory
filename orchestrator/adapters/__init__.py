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


def get_adapter(name: str) -> HarnessAdapter:
    return _REGISTRY[name]()
