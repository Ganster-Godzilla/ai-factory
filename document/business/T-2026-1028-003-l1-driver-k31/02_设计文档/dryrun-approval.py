#!/usr/bin/env python3
"""T-2026-1028-003 批前沙盒预演(ticket-creation-dry-run-gate)。

复制真实 pool 到临时目录,在沙盒里模拟 boss 批准边
(p0_proposed → approval_target,L3 快速通道应为 p3_queued),
验证状态机/级别闸/产物门禁全过。真实 pool 零触碰。
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.daemon.statemachine import approval_target, transition  # noqa: E402
from orchestrator.daemon.ticket import load_ticket  # noqa: E402

TID = "T-2026-1028-003"

src_pool = ROOT / "pool"
fails = []

with tempfile.TemporaryDirectory() as td:
    sandbox_pool = Path(td) / "pool"
    # 只复制状态承载件:tickets + events;日志/pid/ledger 与迁移无关
    (sandbox_pool / "tickets").mkdir(parents=True)
    shutil.copy2(src_pool / "tickets" / f"{TID}.yaml", sandbox_pool / "tickets" / f"{TID}.yaml")
    for ev in src_pool.glob("events*.jsonl*"):
        shutil.copy2(ev, sandbox_pool / ev.name)
    evdir = src_pool / "events"
    if evdir.is_dir():
        shutil.copytree(evdir, sandbox_pool / "events")

    t = load_ticket(sandbox_pool, TID)
    target = approval_target(t)
    print(f"[dry-run] state={t.state} level={t.level} approval_target={target}")
    if target != "p3_queued":
        fails.append(f"approval_target 期望 p3_queued(L3 快速通道),实得 {target}")

    try:
        t2 = transition(sandbox_pool, t, target, actor="boss", project_dir=ROOT)
        print(f"[dry-run] transition OK: p0_proposed -> {t2.state} (owner={t2.owner_role})")
    except Exception as e:  # noqa: BLE001 —— 预演就是要捕获一切拦路异常
        fails.append(f"transition 被拦: {type(e).__name__}: {e}")

    # 沙盒内回读验证落盘
    t3 = load_ticket(sandbox_pool, TID)
    if t3.state != "p3_queued":
        fails.append(f"沙盒落盘状态异常: {t3.state}")

# 真实 pool 未动校验
real = load_ticket(src_pool, TID)
if real.state != "p0_proposed":
    fails.append(f"真实 pool 状态被污染: {real.state}")

if fails:
    print("DRY-RUN FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("DRY-RUN OK(真实 pool 保持 p0_proposed,待 boss 点击)")
