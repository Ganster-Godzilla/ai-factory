#!/usr/bin/env bash
cd "$(dirname "$0")/.."
ROOT="$PWD"
source scripts/lib/profile.sh
FIX=$(mktemp -d); trap 'rm -rf "$FIX"' EXIT
fail=0

bash scripts/init-project.sh --dir "$FIX" --name "demo-proj" --type "单元测试夹具" \
  --language python --lint-cmd "python -m pyflakes {changed_files}" --test-cmd "pytest tests/" \
  || { echo "FAIL: init 非零退出"; fail=1; }

for f in CLAUDE.md backlog.md stack-profile.yaml .claude/state.json .claude/memory/MEMORY.md .claude/rules-registry.md; do
  [ -f "$FIX/$f" ] || { echo "FAIL: 缺 $f"; fail=1; }
done
[ "$(profile_get "$FIX/stack-profile.yaml" project.name)" = "demo-proj" ] || { echo "FAIL: profile name 未渲染"; fail=1; }
[ "$(profile_get "$FIX/stack-profile.yaml" stack.language)" = "python" ] || { echo "FAIL: language 未渲染"; fail=1; }
grep -q "demo-proj" "$FIX/CLAUDE.md" || { echo "FAIL: CLAUDE.md 未渲染"; fail=1; }
grep -q '{{PROJECT_NAME}}' "$FIX/CLAUDE.md" && { echo "FAIL: 占位符残留"; fail=1; }

# 防覆盖:二次运行必须拒绝(不加 --force)
if bash scripts/init-project.sh --dir "$FIX" --name "demo-proj" --type "x" 2>/dev/null; then
  echo "FAIL: 二次运行未拒绝覆盖"; fail=1
fi
# --force 显式重建必须成功
bash scripts/init-project.sh --dir "$FIX" --name "demo-proj" --type "x" --force >/dev/null \
  || { echo "FAIL: --force 未生效"; fail=1; }

# 项目隔离:子目录含骨架的容器目录必须拒绝初始化
CON="$FIX/container"; mkdir -p "$CON/proj-a/.claude"
echo '{}' > "$CON/proj-a/.claude/state.json"
if bash scripts/init-project.sh --dir "$CON" --name "x" --type "x" 2>/dev/null; then
  echo "FAIL: 容器目录未拒绝"; fail=1
fi
# 容器内的新子目录必须可初始化,且自动补写 settings.json
bash scripts/init-project.sh --dir "$CON/proj-b" --name "proj-b" --type "x" >/dev/null \
  || { echo "FAIL: 容器内新子目录初始化失败"; fail=1; }
[ -f "$CON/proj-b/.claude/settings.json" ] || { echo "FAIL: 未补写 settings.json"; fail=1; }
# 已有 settings.json 不得被覆盖
mkdir -p "$CON/proj-c/.claude"
echo '{"custom":true}' > "$CON/proj-c/.claude/settings.json"
bash scripts/init-project.sh --dir "$CON/proj-c" --name "proj-c" --type "x" >/dev/null \
  || { echo "FAIL: proj-c 初始化失败"; fail=1; }
grep -q '"custom":true' "$CON/proj-c/.claude/settings.json" || { echo "FAIL: 已有 settings.json 被覆盖"; fail=1; }

[ "$fail" -eq 0 ] && echo "test_init PASS"
exit "$fail"
