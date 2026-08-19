#!/usr/bin/env bash
# PreToolUse(Write|Edit) hook:命中 stack-profile.yaml 的 security.protected_paths → 要求确认
input=$(cat)
file_path=$(printf '%s' "$input" | python -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)
[ -z "$file_path" ] && exit 0
profile="stack-profile.yaml"
[ -f "$profile" ] || exit 0
source "$(dirname "$0")/lib/profile.sh"
protected=$(profile_array "$profile" "security.protected_paths")
[ -z "$protected" ] && exit 0
for pat in $protected; do
  case "$file_path" in
    *"$pat"*)
      python -c "import json,sys;sys.stdout.reconfigure(encoding='utf-8',newline='\n');print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'ask','permissionDecisionReason':'ai-factory: 命中保护路径 %s — 请确认写入必要性' % sys.argv[1]}},ensure_ascii=False))" "$pat"
      exit 0
      ;;
  esac
done
exit 0
