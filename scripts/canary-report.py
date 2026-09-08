#!/usr/bin/env python
"""金丝雀周度台账(T-2026-0908-003 R4):分流驾驶员效果度量,只读零写入。

三段输出(markdown):
1. 工单段:窗口内活跃工单 × 级别 × 驾驶员(level 映射)× 一次通过率 × 返工 × consult × suspended
2. relay 段:/__stats 渠道与付费池用量(zy-k2/zy-gpt/zy-ds/kimi 池/ds-flash)
3. 控制台读数段:k3-a/b/c/d 剩余额度手填位(W1 每周抄一次 Kimi 控制台)

用法:python scripts/canary-report.py [--days N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DRIVER_OF = {"L1": "k3", "L2": "k2.6", "L3": "k2.6"}
POOL = Path(__file__).resolve().parent.parent / "pool"
RELAY = "http://127.0.0.1:8787/__stats"


def _load_yaml_head(path: Path) -> dict:
    """免 yaml 依赖的浅解析(本脚本只取头部单值字段)。"""
    d = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(id|type|state|level|project|created_at):\s*(.*)$", line)
        if m:
            d[m.group(1)] = m.group(2).strip()
    return d


def _ticket_rows(days: int) -> list[dict]:
    since = time.time() - days * 86400
    rows = []
    for yf in sorted(POOL.glob("tickets/T-*.yaml")):
        head = _load_yaml_head(yf)
        evf = yf.with_suffix(".events.jsonl")
        if not evf.exists():
            continue
        events = []
        for line in evf.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp()
                if ts >= since:
                    events.append(e)
            except Exception:
                continue
        if not events:
            continue
        # 事件词汇实证(0907-002):task_run{task, attempt, status, verify};
        # consult(会诊);suspended(挂起)
        runs = [e for e in events if e.get("event") == "task_run"]
        tasks_done = [e for e in runs if e.get("status") == "done"]
        first_pass = [e for e in tasks_done if str(e.get("attempt", "1")) == "1"]
        consult = sum(1 for e in events if e.get("event") == "consult")
        susp = sum(1 for e in events if e.get("event") == "suspended")
        level = head.get("level") or "L1"
        rows.append({
            "id": head.get("id", yf.stem), "level": level,
            "type": head.get("type", "?"), "state": head.get("state", "?"),
            "driver": DRIVER_OF.get(level, "k3"),
            "tasks_done": len(tasks_done), "attempts": len(runs),
            "first_pass": len(first_pass),
            "consult": consult, "suspended": susp,
        })
    return rows


def _relay_stats() -> dict | None:
    try:
        with urllib.request.urlopen(RELAY, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out = []
    out.append(f"# 金丝雀台账(近 {args.days} 天,生成于 "
               f"{datetime.now().strftime('%Y-%m-%d %H:%M')})\n")
    out.append("## 1. 工单段(驾驶员=level 映射:L2/L3→k2.6,L1→k3)\n")
    out.append("| 工单 | level | 驾驶员 | 状态 | 完成任务 | 尝试总数 | 一次通过率 | consult | suspended |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    rows = _ticket_rows(args.days)
    for r in rows:
        fpr = f"{r['first_pass']}/{r['tasks_done']}" if r["tasks_done"] else "-"
        out.append(f"| {r['id']} | {r['level']} | {r['driver']} | {r['state']} "
                   f"| {r['tasks_done']} | {r['attempts']} | {fpr} | {r['consult']} | {r['suspended']} |")
    if not rows:
        out.append("| (窗口内无活跃工单) | | | | | | | | |")

    out.append("\n## 2. relay 用量段(/__stats 周累计)\n")
    out.append("| 后端 | 请求数 | 周 tokens(M) | 最后使用 |")
    out.append("|---|---|---|---|")
    st = _relay_stats()
    if st is None:
        out.append("| (relay 不可达) | | | |")
    else:
        groups = ["zy-k2", "zy-gpt", "zy-ds", "ds-flash", "glm-flash", "zen-k3"]
        kimi_tot = sum(int(v.get("weekInputTokens", 0)) + int(v.get("weekOutputTokens", 0))
                       for k, v in st.items() if k.startswith("kimi"))
        kimi_req = sum(int(v.get("requests", 0)) for k, v in st.items() if k.startswith("kimi"))
        for name in groups + ["kimi池(合计)"]:
            if name == "kimi池(合计)":
                out.append(f"| {name} | {kimi_req} | {kimi_tot/1e6:.1f} | - |")
            elif name in st:
                v = st[name]
                tot = int(v.get("weekInputTokens", 0)) + int(v.get("weekOutputTokens", 0))
                out.append(f"| {name} | {v.get('requests', 0)} | {tot/1e6:.2f} "
                           f"| {v.get('lastUsed', '-')} |")

    out.append("\n## 3. 控制台读数(手填,Kimi 控制台每周一次)\n")
    out.append("| 账号 | 归属 | 本周剩余额度% | 备注 |")
    out.append("|---|---|---|---|")
    for acc, owner in [("k3-a", "戴鹏"), ("k3-b", "合伙人"), ("k3-c", "合伙人"), ("k3-d", "戴鹏")]:
        out.append(f"| {acc} | {owner} | __(手填)__ | |")

    text = "\n".join(out) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
