#!/usr/bin/env python
"""E2 检查(R8):main 线代码必须能加载真实 pool 的全部工单。
合 main / 重启 dashboard 前跑:python scripts/check-pool-load.py
退出码 0 = 全部可加载;1 = 有工单崩(打印明细)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 脚本直跑也能 import 包

from orchestrator.daemon.ticket import Ticket


def main() -> int:
    pool = Path(__file__).resolve().parent.parent / "pool" / "tickets"
    bad = []
    files = sorted(pool.glob("*.yaml")) if pool.exists() else []
    for f in files:
        try:
            Ticket.load(f)
        except Exception as e:  # noqa: BLE001 — 检查脚本,全类型捕获
            bad.append((f.name, e))
    for name, e in bad:
        print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"checked {len(files)} tickets, {len(bad)} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
