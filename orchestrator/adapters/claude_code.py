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
        # -p 无头模式无人应答权限弹窗(2026-08-28 T-001 冒烟实测);编排器=本地单机+
        # 无人值守+工单由老板本人发起,采用 --dangerously-skip-permissions(用户明确批准)。
        # prompt 走 stdin 不走 argv:Windows .cmd shim 经 cmd.exe 二次解析 argv,
        # pm.md 里的 <工单号> 被当成重定向符号截断参数(进程挂起/输出退化为纯文本)。
        cmd = [exe, "-p", "--output-format", "json",
               "--dangerously-skip-permissions"]
        try:
            r = subprocess.run(cmd, input=packet.prompt, cwd=packet.workdir,
                               capture_output=True,
                               text=True, encoding="utf-8", errors="replace",
                               timeout=packet.timeout)
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        if r.returncode != 0:
            return HarnessResult(status="failed", output=(r.stdout + r.stderr)[:2000])
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            # 非 JSON 输出=参数或流已损坏(历史上曾静默当 done 推进,产物缺失)
            return HarnessResult(status="failed",
                                 output=f"non-json stdout: {r.stdout[:500]}")
        status = "failed" if data.get("is_error") else "done"
        return HarnessResult(status=status,
                             output=str(data.get("result", "")),
                             tokens=data.get("usage", {}))
