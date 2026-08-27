"""模型网关对接:k3 共享池的真实周水位。spec §5.3 双资源台账的联网版。"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from orchestrator.daemon.events import append_event
from orchestrator.daemon.ledger import k3_week_tokens


def gateway_week_tokens(url: str, timeout: float = 5.0) -> int | None:
    try:
        with urllib.request.urlopen(f"{url}/__stats", timeout=timeout) as r:
            stats = json.loads(r.read().decode("utf-8"))
        return sum(int(v.get("weekInputTokens", 0)) + int(v.get("weekOutputTokens", 0))
                   for v in stats.values())
    except Exception:
        return None


def k3_effective_week_tokens(pool: Path, cfg: dict, timeout: float = 5.0) -> int:
    url = (cfg.get("gateway") or {}).get("url")
    if url:
        remote = gateway_week_tokens(url, timeout=timeout)
        if remote is not None:
            return remote
        # 网关配置了但不可达:回退本地台账必须留痕,否则配额闸静默降精度
        append_event(pool, "system", "system", "gateway_fallback",
                     reason="网关不可达,回退本地台账")
    return k3_week_tokens(pool)
