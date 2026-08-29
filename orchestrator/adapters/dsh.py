"""dsh headless 适配器(DeepSeek 角色:开发/脚本级 QA/发布员/SRE 巡检)。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket

PROVIDER_ENV = {"deepseek": "DEEPSEEK_API_KEY", "glm": "ZHIPU_API_KEY"}

# usage trailer 契约(T-2026-0828-003 设计 D3)+ 会话文件真实计量(T-2026-0829-002):
# 优先级链 trailer 精确值 > 解析 ~/.dsh/sessions 会话文件(真实,estimated=False) >
# 双缺硬判负 failed+usage_missing(按 est_call_cny 照估,禁记 0,R9)。
USAGE_TRAILER = "__DSH_USAGE__"
USAGE_MISSING_MSG = "dsh 未输出 usage trailer 且会话文件无 usage,判负;已发生调用按次估算入账(禁记 0)"


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

    def __init__(self, keys_dir: Path | None = None, profile: str = "headless",
                 est_call_cny: float = 0.0, rates: dict | None = None,
                 sessions_dir: Path | None = None):
        self.keys_dir = Path(keys_dir) if keys_dir else None
        self.profile = profile
        # 明放估算单价(T-2026-0829-004):无 trailer 时每次调用按此价入账;0=不估(向后兼容)。
        # 负数钳到 0:负账会冲减日现金让双闸失灵(评审 F4)
        self.est_call_cny = max(0.0, float(est_call_cny or 0.0))
        # 真实计量(T-2026-0829-002):会话文件解析;rates=None → 会话命中也不计价
        self.rates = rates
        self.sessions_dir = Path(sessions_dir) if sessions_dir else None

    def _session_usage(self, workdir, since_ms: float):
        """会话源:定位+解析,全链路容错(不可用→None)。"""
        try:
            from orchestrator.adapters.dsh_usage import (DEFAULT_SESSIONS_DIR,
                                                         find_session_file,
                                                         read_session_usage)
        except ImportError as e:
            # 依赖缺失≠无会话:留诊断,否则故障表现为流程停摆难定位(评审)
            import sys
            print(f"[dsh] 会话解析依赖缺失({e}),会话源不可用;"
                  f"请 pip install zstandard(先配镜像)", file=sys.stderr)
            return None
        try:
            sd = self.sessions_dir or DEFAULT_SESSIONS_DIR
            f = find_session_file(sd, workdir, since_ms)
            return read_session_usage(f, since_ms) if f else None
        except Exception:   # noqa: BLE001 — 解析失败=会话源不可用
            return None

    def _real_result(self, status: str, usage: dict, model: str | None,
                     output: str) -> HarnessResult | None:
        """真实计量结果;费率缺失/模型无条目 → None(调用方走 est 兜底,
        不许记 ¥0 真账——R9,评审 F1/F2)。"""
        from orchestrator.adapters.dsh_usage import estimate_cost, rates_for
        rate = rates_for(model, self.rates)
        if rate is None:
            return None
        # 剥离 trailer 标记行:残缺 trailer 不许污染正文(评审)
        body = "\n".join(ln for ln in output.splitlines()
                         if not ln.strip().startswith(USAGE_TRAILER))
        return HarnessResult(
            status=status, output=body, estimated=False, usage_missing=False,
            tokens={"input_tokens": usage["input"],
                    "output_tokens": usage["output"]},
            cost_cny=estimate_cost(rate, usage))

    def _est_fallback(self, status: str, output: str) -> HarnessResult:
        """双缺兜底:判负/超时但照估入账(R9 禁记 0)。"""
        est = self.est_call_cny
        return HarnessResult(status=status, usage_missing=True, output=output,
                             cost_cny=est, estimated=est > 0)

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
        run_start_ms = time.time() * 1000   # 同机时钟无偏移,缓冲只会重算上轮账(评审)
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=packet.timeout, env=self._env())
        except FileNotFoundError:
            return HarnessResult(status="failed", output="dsh 未安装(shutil.which 未找到)")
        except subprocess.TimeoutExpired:
            # 超时也烧了钱:先试会话真实计量(已完成 step 有 usage),双缺照估(评审 F1)
            usage = self._session_usage(packet.workdir, run_start_ms)
            if usage:
                real = self._real_result("timeout", usage, packet.model,
                                         f"timeout {packet.timeout}s")
                if real:
                    return real
            return self._est_fallback("timeout", f"timeout {packet.timeout}s")
        stdout, stderr = r.stdout or "", r.stderr or ""
        parsed = parse_usage_trailer(stdout)
        if parsed is None:
            # 优先级链(T-2026-0829-002):trailer > 会话文件真实计量 > 双缺硬判负照估
            usage = self._session_usage(packet.workdir, run_start_ms)
            if usage:
                body = (stdout + "\n" + stderr) if stderr else stdout
                real = self._real_result(
                    "done" if r.returncode == 0 else "failed",
                    usage, packet.model, body[:4000])
                if real:
                    return real
            return self._est_fallback(
                "failed",     # 恢复硬契约:双源都断没理由放行(boss 决)
                f"[usage_missing] {USAGE_MISSING_MSG}\n"
                f"{(stdout + chr(10) + stderr if stderr else stdout)[:4000]}")
        body, tokens, cost = parsed
        if body and stderr:
            body = f"{body}\n{stderr}"
        else:
            body = body or stderr
        return HarnessResult(status="done" if r.returncode == 0 else "failed",
                             output=body[:4000], tokens=tokens, cost_cny=cost)
