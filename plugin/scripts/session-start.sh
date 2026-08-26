#!/usr/bin/env bash
# SessionStart hook:注入 backlog/state 摘要(stdout 进入上下文,≤40 行)
{
if [ -f backlog.md ]; then
  echo "== Backlog(进行中/阻塞) =="
  sed -n '/## *In Progress/,/^## /p' backlog.md | head -12
  sed -n '/## *Blocked/,/^## /p' backlog.md | head -6
  echo
fi
if [ -f .claude/state.json ]; then
  echo "== 模块状态(非 delivered) =="
  python - <<'PY'
import json, sys
sys.stdout.reconfigure(encoding="utf-8", newline="\n")
try:
    d = json.load(open(".claude/state.json", encoding="utf-8"))
    rows = [(k, v.get("phase","?")) for k,v in d.get("modules",{}).items() if v.get("status")!="delivered"]
    for k,p in rows[:12]:
        print(f"- {k}: {p}")
    b = d.get("budget",{})
    if b: print(f"并发预算: {b.get('currently_executing','?')}/{b.get('concurrent_max','?')}")
except Exception as e:
    print(f"(state.json 解析失败: {e})")
PY
fi
if [ ! -f backlog.md ] && [ ! -f .claude/state.json ]; then
  echo "ai-factory: 未检测到 backlog.md / .claude/state.json — 运行 /ai-factory:ai-init 初始化项目骨架"
fi
} | head -40
exit 0
