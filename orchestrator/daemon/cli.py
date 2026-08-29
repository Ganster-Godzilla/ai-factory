"""orc 命令行:老板与编排器交互的入口。审批=改状态,git 留痕。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from orchestrator.adapters import get_adapter
from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.runner import ROLE_ROUTING, WORK_STATES, advance_once
from orchestrator.daemon.statemachine import (
    APPROVALS, IllegalTransition, resume, suspend, transition,
)
from orchestrator.daemon.ticket import load_ticket, new_ticket


def _cfg() -> dict:
    return yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))


def _pool() -> Path:
    return Path(_cfg()["pool"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orc")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("new"); c.add_argument("project"); c.add_argument("summary"); c.add_argument("--by", default="human")
    c.add_argument("--type", choices=["feature", "incident"], default="feature")
    sub.add_parser("list")
    c = sub.add_parser("show"); c.add_argument("id")
    c = sub.add_parser("approve"); c.add_argument("id"); c.add_argument("--as", dest="actor", default="boss")
    c = sub.add_parser("reject"); c.add_argument("id")
    c.add_argument("--redo", action="store_true",
                   help="驳回回炉:p1_proposed → p1_drafting 让 PM 重做(记 p1_round);"
                        "缺省仍关单。仅 p1_proposed 可用,其余态报错")
    c = sub.add_parser("suspend"); c.add_argument("id"); c.add_argument("reason")
    c = sub.add_parser("resume"); c.add_argument("id")
    c = sub.add_parser("advance"); c.add_argument("id"); c.add_argument("project_dir"); c.add_argument("--fake", action="store_true")
    c.add_argument("--consult-fake", action="store_true")
    c = sub.add_parser("dashboard"); c.add_argument("--port", type=int, default=8321)
    c.add_argument("--host", default="127.0.0.1",
                   help="默认 127.0.0.1 仅本机;局域网开放(0.0.0.0)+认证属 v2 决策")
    args = p.parse_args(argv)
    pool = _pool()

    try:
        if args.cmd == "new":
            t = new_ticket(pool, args.project, args.summary, created_by=args.by,
                           type=args.type)
            print(f"created {t.id} ({t.state})")
        elif args.cmd == "list":
            for f in sorted((pool / "tickets").glob("*.yaml")):
                t = load_ticket(pool, f.stem)
                print(f"{t.id}  [{t.state}]  {t.project}  {t.summary}")
        elif args.cmd == "show":
            t = load_ticket(pool, args.id)
            print(f"{t.id} [{t.state}] owner={t.owner_role} project={t.project}\n{ t.summary}")
            for e in read_events(pool, args.id):
                print(f"  {e['ts'][:19]}  {e['actor']:<10} {e['event']}")
        elif args.cmd == "approve":
            t = load_ticket(pool, args.id)
            if args.actor == "pm" and t.state == "draft":
                transition(pool, t, "p0_proposed", actor="pm")
            else:
                target = APPROVALS.get(t.state)
                if not target:
                    print(f"{t.state} 不是审批态", file=sys.stderr)
                    return 1
                transition(pool, t, target, actor=args.actor)
            print(f"{args.id} → {load_ticket(pool, args.id).state}")
        elif args.cmd == "reject":
            t = load_ticket(pool, args.id)
            if args.redo:
                if t.state != "p1_proposed":
                    # 迁移表只拦非法边,p0→p1_drafting 这类合法边在此被命令语义挡住
                    raise IllegalTransition(
                        f"reject --redo 仅用于 p1_proposed,当前 {t.state}")
                transition(pool, t, "p1_drafting", actor="boss")
                print(f"{args.id} → p1_drafting (round={t.p1_round})")
            else:
                transition(pool, t, "closed", actor="boss")
                print(f"{args.id} → closed")
        elif args.cmd == "suspend":
            suspend(pool, load_ticket(pool, args.id), actor="boss", reason=args.reason,
                    reason_code="manual")
            print(f"{args.id} → suspended")
        elif args.cmd == "resume":
            resume(pool, load_ticket(pool, args.id), actor="boss")
            print(f"{args.id} → resumed")
        elif args.cmd == "advance":
            cfg = _cfg()
            budgets = cfg.get("budgets") or {}
            est = budgets.get("ds_est_call_cny") or 0.0
            if est <= 0:
                # R9 禁记 0:双缺兜底是常设路径(不随 mingfang 结束),
                # 估算缺失等于给烧钱的调用开零账黑洞(评审)——兜底价 + 显式警告
                est = 0.05
                print("warn: ds_est_call_cny 缺失/为 0,双缺兜底按 ¥0.05/次 估算入账",
                      file=sys.stderr)
            adapter = FakeHarness() if args.fake else get_adapter(
                ROLE_ROUTING.get(
                    WORK_STATES.get(load_ticket(pool, args.id).state, "dev"), "dsh"),
                keys_dir=cfg.get("keys_dir"), est_call_cny=est,
                rates=cfg.get("rates"))
            print(advance_once(pool, args.id, adapter, Path(args.project_dir),
                               cfg=cfg,
                               consult_adapter=FakeHarness() if args.consult_fake else None))
        elif args.cmd == "dashboard":
            from orchestrator.dashboard.app import create_app
            create_app(_pool(), _cfg()).run(host=args.host, port=args.port, debug=False)
    except (IllegalTransition, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
