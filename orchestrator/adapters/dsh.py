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

    def _file_key(self, provider: str) -> str | None:
        """keys_dir/<provider>.env 里的有效 key;文件缺失/空值/TODO 占位 → None。"""
        if not self.keys_dir:
            return None
        f = self.keys_dir / f"{provider}.env"
        if not f.exists():
            return None
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("KEY=") and not line.startswith("#"):
                v = line[4:].strip()
                return v if v and not v.startswith("TODO") else None
        return None

    def _env(self) -> dict:
        env = dict(os.environ)
        for provider, env_name in PROVIDER_ENV.items():
            v = self._file_key(provider)
            if v is not None:  # 占位/空值不注入,不覆盖 os.environ 已有真 key
                env[env_name] = v
        return env

    def run(self, packet: TaskPacket) -> HarnessResult:
        # fail-fast:目标 provider 的 env 文件存在但只有占位 key,且环境也没有真 key,
        # 直接失败,不把必然 401 的调用打进 subprocess
        if self.keys_dir:
            f = self.keys_dir / "deepseek.env"
            if (f.exists() and self._file_key("deepseek") is None
                    and not os.environ.get(PROVIDER_ENV["deepseek"])):
                return HarnessResult(status="failed", output=f"key 未填: {f.name}")
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
