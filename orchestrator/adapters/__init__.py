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


def get_adapter(name: str, keys_dir=None, est_call_cny: float = 0.0,
                rates: dict | None = None) -> HarnessAdapter:
    if name == "dsh":
        # est_call_cny:双缺兜底估算价(T-2026-0829-004);rates:会话真实计量费率表(T-2026-0829-002)
        return DshAdapter(keys_dir=keys_dir, est_call_cny=est_call_cny,
                          rates=rates)
    return _REGISTRY[name]()
