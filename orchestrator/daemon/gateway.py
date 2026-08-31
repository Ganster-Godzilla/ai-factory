"""模型网关对接:k3 共享池的真实周水位。spec §5.3 双资源台账的联网版。"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from orchestrator.daemon.events import append_event
from orchestrator.daemon.ledger import k3_week_tokens


def gateway_week_tokens(url: str, timeout: float = 5.0) -> int | None:
    """k3 共享池周水位:只合计 kimi* 后端。

    zen-kimi 等付费兜底后端(T-2026-0901-001)走现金台账对账,
    不计入 k3 共享池水位——否则兜底一承接就污染 150M 预算闸(T-001 类误触)。
    """
    try:
        with urllib.request.urlopen(f"{url}/__stats", timeout=timeout) as r:
            stats = json.loads(r.read().decode("utf-8"))
        return sum(int(v.get("weekInputTokens", 0)) + int(v.get("weekOutputTokens", 0))
                   for k, v in stats.items() if k.startswith("kimi"))
    except Exception:
        return None


def k3_effective_week_tokens(pool: Path, cfg: dict, timeout: float = 5.0,
                             trace: bool = True) -> int:
    url = (cfg.get("gateway") or {}).get("url")
    if url:
        remote = gateway_week_tokens(url, timeout=timeout)
        if remote is not None:
            return remote
        # 网关配置了但不可达:回退本地台账必须留痕,否则配额闸静默降精度。
        # trace=False 用于总览页 GET 等高频只读路径(终审 F1:GET 不写事件)。
        if trace:
            append_event(pool, "system", "system", "gateway_fallback",
                         reason="网关不可达,回退本地台账")
    return k3_week_tokens(pool)
