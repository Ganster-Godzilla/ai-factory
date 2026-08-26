"""orc 命令行:老板与编排器交互的入口。审批=改状态,git 留痕。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from orchestrator.adapters.fake import FakeHarness
from orchestrator.daemon.events import read_events
from orchestrator.daemon.runner import advance_once
from orchestrator.daemon.statemachine import (
    APPROVALS, IllegalTransition, resume, suspend, transition,
)
from orchestrator.daemon.ticket import load_ticket, new_ticket


def _pool() -> Path:
    cfg = yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))
    return Path(cfg["pool"])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orc")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("new"); c.add_argument("project"); c.add_argument("summary"); c.add_argument("--by", default="human")
    sub.add_parser("list")
    c = sub.add_parser("show"); c.add_argument("id")
    c = sub.add_parser("approve"); c.add_argument("id"); c.add_argument("--as", dest="actor", default="boss")
    c = sub.add_parser("reject"); c.add_argument("id")
    c = sub.add_parser("suspend"); c.add_argument("id"); c.add_argument("reason")
    c = sub.add_parser("resume"); c.add_argument("id")
    c = sub.add_parser("advance"); c.add_argument("id"); c.add_argument("project_dir"); c.add_argument("--fake", action="store_true")
    args = p.parse_args(argv)
    pool = _pool()

    try:
        if args.cmd == "new":
            t = new_ticket(pool, args.project, args.summary, created_by=args.by)
            print(f"created {t.id} (draft)")
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
            transition(pool, load_ticket(pool, args.id), "closed", actor="boss")
            print(f"{args.id} → closed")
        elif args.cmd == "suspend":
            suspend(pool, load_ticket(pool, args.id), actor="boss", reason=args.reason)
            print(f"{args.id} → suspended")
        elif args.cmd == "resume":
            resume(pool, load_ticket(pool, args.id), actor="boss")
            print(f"{args.id} → resumed")
        elif args.cmd == "advance":
            if not args.fake:
                print("真实适配器未接入(M2),请用 --fake", file=sys.stderr)
                return 1
            print(advance_once(pool, args.id, FakeHarness(), Path(args.project_dir)))
    except (IllegalTransition, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
