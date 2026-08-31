#!/usr/bin/env python
"""Zen 兜底消耗周对账(T-2026-0901-001,R9 账不可瞎)。

读 relay /__stats 的 zen-kimi 周 tokens,按 orchestrator.yaml rates.opencode
折算 CNY 入 ledger(estimated=true,复审对账用)。幂等:同一 ISO 周已入过账则跳过。
用法:
  python scripts/zen-usage-ledger.py            # 入账(本周未入过才写)
  python scripts/zen-usage-ledger.py --dry-run  # 只打印,不写台账
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 脚本直跑也能 import 包

import yaml  # noqa: E402

from orchestrator.daemon.ledger import append_ledger  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def iso_week_id(d: date | None = None) -> str:
    y, w, _ = (d or date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def fetch_zen_week(url: str, timeout: float = 5.0) -> dict | None:
    """relay /__stats → zen-kimi 的 {weekId, input, output};不可达/无此后端 → None。"""
    with urllib.request.urlopen(f"{url}/__stats", timeout=timeout) as r:
        stats = json.loads(r.read().decode("utf-8"))
    b = stats.get("zen-kimi")
    if not b:
        return None
    return {"weekId": b.get("weekId") or iso_week_id(),
            "input": int(b.get("weekInputTokens", 0)),
            "output": int(b.get("weekOutputTokens", 0))}


def week_cost_cny(week: dict, rates: dict) -> float:
    return round(week["input"] / 1e6 * float(rates.get("input_per_m", 0))
                 + week["output"] / 1e6 * float(rates.get("output_per_m", 0)), 4)


def already_recorded(pool: Path, week_id: str) -> bool:
    f = pool / "ledger.jsonl"
    if not f.exists():
        return False
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("resource") == "opencode" and (e.get("tokens") or {}).get("weekId") == week_id:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "orchestrator.yaml").read_text(encoding="utf-8"))
    url = (cfg.get("gateway") or {}).get("url")
    rates = (cfg.get("rates") or {}).get("opencode") or {}
    pool = ROOT / cfg.get("pool", "pool")
    if not url:
        print("orchestrator.yaml 无 gateway.url", file=sys.stderr)
        return 1

    try:
        week = fetch_zen_week(url)
    except Exception as e:
        print(f"relay 不可达({url}):{e}", file=sys.stderr)
        return 1
    if week is None:
        print("/__stats 无 zen-kimi 后端,无需对账")
        return 0
    cost = week_cost_cny(week, rates)
    print(f"zen-kimi {week['weekId']}: input={week['input']} output={week['output']} "
          f"→ ¥{cost}(rates {rates.get('input_per_m')}/{rates.get('output_per_m')} per 1M)")
    if week["input"] == 0 and week["output"] == 0:
        print("本周无消耗,不入账")
        return 0
    if already_recorded(pool, week["weekId"]):
        print(f"{week['weekId']} 已入过账,跳过(幂等)")
        return 0
    if args.dry_run:
        print("dry-run:不写台账")
        return 0
    entry = append_ledger(pool, "opencode", cost, "cny", "ops-zen-reconcile", "sre",
                          "kimi-k2.5",
                          tokens={"weekId": week["weekId"],
                                  "input": week["input"], "output": week["output"]},
                          calls=0, estimated=True)
    print(f"已入账:{entry['ts']} estimated=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
