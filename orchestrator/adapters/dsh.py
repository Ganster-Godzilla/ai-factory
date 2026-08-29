"""dsh headless 适配器(DeepSeek 角色:开发/脚本级 QA/发布员/SRE 巡检)。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket

PROVIDER_ENV = {"deepseek": "DEEPSEEK_API_KEY", "glm": "ZHIPU_API_KEY"}

# usage trailer 硬契约(T-2026-0828-003 设计 D3):dsh headless 结束时在 stdout 末行输出
# `__DSH_USAGE__ {"input_tokens":N, "output_tokens":N, "cost_cny":X.XX}`;
# adapter 解析并剥离 trailer 填入 HarnessResult.tokens/cost_cny。解析不到 trailer
# (旧版 dsh)→ status=failed + usage_missing=True:无账不推进,runner 记 usage_missing 事件。
USAGE_TRAILER = "__DSH_USAGE__"
USAGE_MISSING_MSG = "dsh 未输出 usage trailer,台账无证据,视同失败"


def parse_usage_trailer(stdout: str) -> tuple[str, dict, float] | None:
    """解析 stdout 末行 usage trailer。返回 (剥离 trailer 的正文, tokens, cost_cny);
    无 trailer / 不在末行 / JSON 损坏 / 缺键 → None(契约未满足,一律视同缺失)。"""
    lines = (stdout or "").splitlines()
    while lines and not lines[-1].strip():   # 容忍 trailer 之后的空行
        lines.pop()
    if not lines:
        return None
    last = lines[-1].strip()
    if not last.startswith(USAGE_TRAILER):
        return None
    try:
        data = json.loads(last[len(USAGE_TRAILER):].strip())
        if not isinstance(data, dict):
            return None
        tokens = {"input_tokens": int(data["input_tokens"] or 0),
                  "output_tokens": int(data["output_tokens"] or 0)}
        cost = float(data["cost_cny"] or 0.0)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return "\n".join(lines[:-1]).rstrip("\n"), tokens, cost


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
        stdout, stderr = r.stdout or "", r.stderr or ""
        parsed = parse_usage_trailer(stdout)
        if parsed is None:
            # 无账不推进(D3):旧版 dsh / 输出被截断吞掉 trailer → failed + usage_missing
            return HarnessResult(
                status="failed", usage_missing=True,
                output=f"{USAGE_MISSING_MSG}\n--- 原始输出(截断) ---\n{(stdout + stderr)[:500]}")
        body, tokens, cost = parsed
        if body and stderr:
            body = f"{body}\n{stderr}"
        else:
            body = body or stderr
        return HarnessResult(status="done" if r.returncode == 0 else "failed",
                             output=body[:4000], tokens=tokens, cost_cny=cost)
