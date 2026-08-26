"""Claude Code headless 适配器(k3 角色:PM/架构师/测试设计师/视觉 QA/会诊)。"""
from __future__ import annotations

import json
import subprocess

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class ClaudeCodeAdapter(HarnessAdapter):
    name = "claude_code"

    def run(self, packet: TaskPacket) -> HarnessResult:
        cmd = ["claude", "-p", packet.prompt, "--output-format", "json"]
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=packet.timeout)
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        if r.returncode != 0:
            return HarnessResult(status="failed", output=(r.stdout + r.stderr)[:2000])
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return HarnessResult(status="done", output=r.stdout)
        status = "failed" if data.get("is_error") else "done"
        return HarnessResult(status=status,
                             output=str(data.get("result", "")),
                             tokens=data.get("usage", {}))
