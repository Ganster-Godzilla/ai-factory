"""Harness 适配器契约。编排器与 CC/dsh 之间的唯一接触面。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TaskPacket:
    role: str
    prompt: str
    workdir: Path
    artifacts_in: list = field(default_factory=list)
    artifacts_out: list = field(default_factory=list)
    acceptance_cmd: str | None = None
    budget: dict = field(default_factory=dict)
    timeout: int = 1800
    model: str | None = None


@dataclass
class HarnessResult:
    status: str            # done | failed | timeout
    output: str = ""
    tokens: dict = field(default_factory=dict)
    cost_cny: float = 0.0
    log_path: str | None = None
    # dsh usage trailer 缺失标记(D3 无账不推进);其他 harness 恒为 False
    usage_missing: bool = False


class HarnessAdapter(ABC):
    name: str

    @abstractmethod
    def run(self, packet: TaskPacket) -> HarnessResult:
        ...
