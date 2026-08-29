#!/usr/bin/env bash
# PreToolUse(Bash) hook:git push 前跑 stack-profile.yaml 的 stack.lint_cmd
# 退出码:0=放行;2=阻断(stderr 回传给模型)
input=$(cat)
cmd=$(printf '%s' "$input" | python -c "import sys,json;print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)
case "$cmd" in
  *"git push"*) ;;
  *) exit 0 ;;
esac
profile="stack-profile.yaml"
[ -f "$profile" ] || exit 0   # 无 profile 降级不动作
source "$(dirname "$0")/lib/profile.sh"
lint_cmd=$(profile_get "$profile" "stack.lint_cmd")
[ -z "$lint_cmd" ] && exit 0

if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
  changed=$(git diff --name-only '@{u}..HEAD')
else
  changed=$(git status --porcelain | awk '{print $2}')
fi
files=""
# 只喂 Python 文件:lint_cmd 是 pyflakes,md/yaml/html 会让它误报(2026-08-29 事故)
for f in $changed; do
  case "$f" in
    *.py) [ -f "$f" ] && files="$files $f" ;;
  esac
done
[ -z "$files" ] && exit 0

run_cmd="${lint_cmd//\{changed_files\}/$files}"
if ! eval "$run_cmd" >&2; then
  echo "ai-factory[pre-push-lint]: lint 未通过,push 已阻断。修复后重试。命令: $run_cmd" >&2
  exit 2
fi
exit 0
