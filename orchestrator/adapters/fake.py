"""测试用假 harness:按脚本返回,不调用任何真实模型。"""
from __future__ import annotations

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class FakeHarness(HarnessAdapter):
    name = "fake"

    def __init__(self, script: list[str] | None = None):
        self._script = list(script or [])
        self.received: list[TaskPacket] = []

    def run(self, packet: TaskPacket) -> HarnessResult:
        self.received.append(packet)
        status = self._script.pop(0) if self._script else "done"
        return HarnessResult(status=status, output=f"fake:{packet.role}:{status}")
