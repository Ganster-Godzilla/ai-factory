"""dsh headless 适配器(DeepSeek 角色:开发/脚本级 QA/发布员/SRE 巡检)。"""
from __future__ import annotations

import subprocess

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class DshAdapter(HarnessAdapter):
    name = "dsh"

    def run(self, packet: TaskPacket) -> HarnessResult:
        cmd = ["dsh", "--profile", "headless", packet.prompt]
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=packet.timeout)
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        output = (r.stdout + r.stderr)[:4000]
        return HarnessResult(status="done" if r.returncode == 0 else "failed",
                             output=output)
