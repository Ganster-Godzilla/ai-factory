"""Claude Code headless 适配器(k3 角色:PM/架构师/测试设计师/视觉 QA/会诊)。"""
from __future__ import annotations

import json
import shutil
import subprocess

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket


class ClaudeCodeAdapter(HarnessAdapter):
    name = "claude_code"

    def run(self, packet: TaskPacket) -> HarnessResult:
        # Windows 上 npm 安装的 claude 是 .cmd shim,CreateProcess 只自动补 .exe;
        # shutil.which 解析出带扩展名的全路径(POSIX 同样返回真实路径),缺失时回退裸名。
        exe = shutil.which("claude") or "claude"
        # -p 无头模式无人应答权限弹窗,写文件/Bash 会被静默拒绝(2026-08-28 T-001 冒烟实测:
        # acceptEdits 只放行写/编辑,角色调 Bash 仍被拒,PM 两次返回"需要授权"文本但
        # status=done 照常推进)。编排器场景=本地单机+无人值守+工单摘要由老板本人撰写,
        # 采用 --dangerously-skip-permissions(CI 惯例);风险面受控,沙箱化留待 M5。
        cmd = [exe, "-p", packet.prompt, "--output-format", "json",
               "--dangerously-skip-permissions"]
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
