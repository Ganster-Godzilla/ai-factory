#!/usr/bin/env python
"""E2 检查(R8):main 线代码必须能加载真实 pool 的全部工单。
合 main / 重启 dashboard 前跑:python scripts/check-pool-load.py
退出码 0 = 全部可加载;1 = 有工单崩(打印明细)。

E2 检查(R10,2026-09-01 晋升):工单账本不得与执行脱钩。
  a) p3_running 及以后状态的工单,tasks 必须非空(执行中却"暂无任务"=脱钩);
  b) p2_approved/p3_queued 工单的 artifacts 含 *_commit 键 = 执行已发生但
     任务未灌/状态未推进(2026-09-01 T-2026-0901-001 事故形态)。
历史工单(id < T-2026-0901)只加载校验,豁免 R10 检查(规则生效前)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 脚本直跑也能 import 包

from orchestrator.daemon.ticket import Ticket

R10_EFFECTIVE_ID = "T-2026-0901"          # R10 E2 生效起点(含)
EXEC_STATES = {"p3_running", "p4_verifying", "p5_ready", "p5_releasing",
               "monitoring", "done"}
PRE_EXEC_STATES = {"p2_approved", "p3_queued"}


def r10_violations(t: Ticket) -> list[str]:
    if t.id < R10_EFFECTIVE_ID:            # 字符串序即日期序,历史单豁免
        return []
    v = []
    if t.state in EXEC_STATES and not t.tasks:
        v.append(f"{t.state} 状态但 tasks 为空(执行脱钩)")
    if t.state in PRE_EXEC_STATES:
        commits = [k for k in (t.artifacts or {}) if k.endswith(("_commit", "_commits"))]
        if commits:
            v.append(f"{t.state} 但 artifacts 已挂提交 {commits}(先灌任务推进 p3)")
    return v


def main() -> int:
    pool = Path(__file__).resolve().parent.parent / "pool" / "tickets"
    bad = []
    files = sorted(pool.glob("*.yaml")) if pool.exists() else []
    for f in files:
        try:
            t = Ticket.load(f)
            for v in r10_violations(t):
                bad.append((f.name, RuntimeError(f"R10: {v}")))
        except Exception as e:  # noqa: BLE001 — 检查脚本,全类型捕获
            bad.append((f.name, e))
    for name, e in bad:
        print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"checked {len(files)} tickets, {len(bad)} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
