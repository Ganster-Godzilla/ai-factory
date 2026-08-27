"""dsh headless 适配器(DeepSeek 角色:开发/脚本级 QA/发布员/SRE 巡检)。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket

PROVIDER_ENV = {"deepseek": "DEEPSEEK_API_KEY", "zhipu": "ZHIPU_API_KEY"}


class DshAdapter(HarnessAdapter):
    name = "dsh"

    def __init__(self, keys_dir: Path | None = None, profile: str = "headless"):
        self.keys_dir = Path(keys_dir) if keys_dir else None
        self.profile = profile

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.keys_dir:
            for provider, env_name in PROVIDER_ENV.items():
                f = self.keys_dir / f"{provider}.env"
                if f.exists():
                    for line in f.read_text(encoding="utf-8").splitlines():
                        if line.startswith("KEY=") and not line.startswith("#"):
                            env[env_name] = line[4:].strip()
        return env

    def run(self, packet: TaskPacket) -> HarnessResult:
        exe = shutil.which("dsh") or "dsh"
        profile = f"headless-{packet.model}" if packet.model else self.profile
        cmd = [exe, "--profile", profile, packet.prompt]
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=packet.timeout, env=self._env())
        except FileNotFoundError:
            return HarnessResult(status="failed", output="dsh 未安装(shutil.which 未找到)")
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        output = (r.stdout + r.stderr)[:4000]
        return HarnessResult(status="done" if r.returncode == 0 else "failed", output=output)
