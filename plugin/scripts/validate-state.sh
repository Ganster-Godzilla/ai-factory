#!/usr/bin/env bash
# Stop hook:代码有变更而 backlog.md/state.json 未同步 → systemMessage 警告(不阻断)
cat >/dev/null   # 消费 stdin
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
changed=$(git status --porcelain 2>/dev/null)
[ -z "$changed" ] && exit 0
state_touched=$(printf '%s\n' "$changed" | grep -c -E '(backlog\.md|state\.json)')
code_touched=$(printf '%s\n' "$changed" | grep -v -E '(backlog\.md|state\.json|docs/|document/|\.claude/)' \
               | grep -c -E '\.(py|js|ts|xml|sh|sql|java|go|rs|vue|owl)')
if [ "${code_touched:-0}" -gt 0 ] && [ "${state_touched:-0}" -eq 0 ]; then
  python -c "import json,sys;sys.stdout.reconfigure(encoding='utf-8',newline='\n');print(json.dumps({'systemMessage':'⚠️ ai-factory: 检测到代码变更,但 backlog.md / state.json 未同步。结束会话前请运行 /ai-factory:backlog-sync 回写进度。'},ensure_ascii=False))"
fi
exit 0
