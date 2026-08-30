#!/usr/bin/env python
"""smoke —— 后端冒烟验证(不依赖 .env / 密钥 / 外网)。

S1 任务件:为 T2 拆分提供"每步必跑"的最小行为验证。

步骤:
1. compileall apps/api(排除 .venv/__pycache__)—— 语法层检查;
2. 在空闲端口启动 uvicorn(main:app,与 start-sk2.ps1 同一入口,
   lifespan 会真实执行建库与中断恢复);
3. GET /api/health      期望 200,且 body.services 含 comfyui/ollama 键
   (离线时取值为 false 属正常,只验结构不验可用性);
4. GET /openapi.json    期望 200,且 paths 非空;
5. GET /api/providers   期望 200,且 providers 列表非空。

全部通过 → 退出码 0;任一失败 → 打印 uvicorn 日志尾部,退出码 1。

用法:
    python smoke.py [--port N] [--timeout-seconds 120]
需要 apps/api/.venv,通常经 tools/validate.ps1 smoke 调用。
"""

from __future__ import annotations

import argparse
import compileall
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"
HOST = "127.0.0.1"

_LOG_TAIL_LINES = 60


class SmokeFailure(Exception):
    """单个冒烟断言失败。"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _compile_backend() -> None:
    ok = compileall.compile_dir(
        str(API_DIR),
        quiet=2,
        rx=re.compile(r"[\\/]\.venv[\\/]|[\\/]__pycache__[\\/]"),
        force=False,
    )
    if not ok:
        raise SmokeFailure("compileall apps/api 失败:存在语法错误")


def _get_json(base_url: str, path: str, timeout: float = 30.0) -> tuple[int, Any]:
    response = httpx.get(f"{base_url}{path}", timeout=timeout)
    try:
        body: Any = response.json()
    except json.JSONDecodeError:
        body = None
    return response.status_code, body


def _wait_until_up(
    proc: subprocess.Popen[Any], base_url: str, timeout: float
) -> None:
    # 每个请求给足超时:本机网络栈对"连接关闭端口"不立刻拒绝,
    # /api/health 的 ollama/comfyui 探测会吃满应用内 httpx 超时(实测 ~11s),
    # 单请求超时必须远大于该值,否则永远等不到 200。
    request_timeout = max(30.0, min(timeout / 3.0, 60.0))
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            raise SmokeFailure(f"uvicorn 提前退出(exit {code}),尚未就绪")
        try:
            status, _ = _get_json(base_url, "/api/health", timeout=request_timeout)
            if status == 200:
                return
            last_error = f"HTTP {status}"
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
        time.sleep(1.0)
    raise SmokeFailure(f"服务在 {timeout:.0f}s 内未就绪(最后状态:{last_error})")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="后端冒烟验证")
    parser.add_argument("--port", type=int, default=0, help="指定端口;缺省自动选空闲端口")
    parser.add_argument(
        "--timeout-seconds", type=float, default=120.0, help="等待服务就绪的超时秒数"
    )
    args = parser.parse_args()

    checks: list[tuple[str, str]] = []

    def record(name: str, detail: str) -> None:
        checks.append((name, detail))
        print(f"[smoke] PASS {name}: {detail}")

    port = args.port if args.port > 0 else _free_port()
    base_url = f"http://{HOST}:{port}"

    try:
        _compile_backend()
        record("compile", f"apps/api 语法检查通过({API_DIR.name})")
    except SmokeFailure as exc:
        print(f"[smoke] FAIL {exc}")
        return 1

    # ignore_cleanup_errors: Windows 上若句柄释放时序异常,日志文件可能短暂数据
    # 锁定;日志只是诊断辅助,清理失败不应污染退出码(句柄仍会显式关闭)。
    with tempfile.TemporaryDirectory(
        prefix="sk2-smoke-", ignore_cleanup_errors=True
    ) as log_dir:
        log_path = Path(log_dir) / "uvicorn.log"
        # 显式持有日志句柄并在子进程被回收后关闭:内联 open() 会让父进程
        # 句柄游离,Windows 上 TemporaryDirectory 清理将因 WinError 32 崩溃。
        log_handle = log_path.open("w", encoding="utf-8")
        try:
            proc = subprocess.Popen(  # noqa: S603 —— 固定 argv,无外部输入
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "main:app",
                    "--host",
                    HOST,
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                ],
                cwd=str(API_DIR),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        except Exception:
            log_handle.close()
            raise
        try:
            try:
                _wait_until_up(proc, base_url, args.timeout_seconds)
                record("boot", f"uvicorn main:app 启动并就绪 {base_url}")

                status, body = _get_json(base_url, "/api/health")
                services = (body or {}).get("services") if isinstance(body, dict) else None
                _expect(
                    status == 200
                    and isinstance(services, dict)
                    and "comfyui" in services
                    and "ollama" in services,
                    f"/api/health 异常:HTTP {status} body={str(body)[:200]}",
                )
                record(
                    "health",
                    f"/api/health 200(comfyui={services['comfyui']}, "
                    f"ollama={services['ollama']}, 离线为 false 属正常)",
                )

                status, body = _get_json(base_url, "/openapi.json")
                paths = (body or {}).get("paths") if isinstance(body, dict) else None
                _expect(
                    status == 200 and isinstance(paths, dict) and len(paths) > 0,
                    f"/openapi.json 异常:HTTP {status}",
                )
                record("openapi", f"/openapi.json 200,paths={len(paths)}")

                status, body = _get_json(base_url, "/api/providers")
                providers = (body or {}).get("providers") if isinstance(body, dict) else None
                _expect(
                    status == 200
                    and isinstance(providers, list)
                    and len(providers) > 0,
                    f"/api/providers 异常:HTTP {status}",
                )
                record("providers", f"/api/providers 200,providers={len(providers)}")
            except SmokeFailure as exc:
                print(f"[smoke] FAIL {exc}")
                tail = log_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()[-_LOG_TAIL_LINES:]
                if tail:
                    print("[smoke] ---- uvicorn 日志尾部 ----")
                    for line in tail:
                        print(f"[smoke] | {line}")
                return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            # 子进程被回收后再关日志句柄,否则 Windows 清理临时目录会炸
            log_handle.close()

    print(f"[smoke] 全部通过({len(checks)} 项)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
