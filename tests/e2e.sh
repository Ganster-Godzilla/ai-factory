#!/usr/bin/env bash
# e2e.sh — scratch 项目端到端验证(spec §十二)
# scratch 项目需要 git init(pre-push-lint 依赖 git);ai-factory 自身不做 git,两者不冲突
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRATCH="${1:-/d/workspace/tmp/ai-factory-e2e}"
rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"; cd "$SCRATCH"

# 1. ai-init 初始化
bash "$ROOT/scripts/init-project.sh" --dir . --name "e2e-demo" --type "E2E 验证" \
  --language python --lint-cmd "bash -c '! grep -l FAILMARKER {changed_files}'" --test-cmd "true" >/dev/null
for f in stack-profile.yaml backlog.md .claude/state.json CLAUDE.md; do
  [ -f "$f" ] || { echo "E2E FAIL: 骨架缺 $f"; exit 1; }
done

# 2. git + 场景 A:lint 失败 → push 被阻断(exit 2)
git init -q; git config user.email t@t; git config user.name t
git add -A && git commit -qm init   # 先提交骨架,保证后续变更集只含测试文件
echo "FAILMARKER" > bad.py
PUSH_JSON='{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'
if printf '%s' "$PUSH_JSON" | bash "$ROOT/scripts/pre-push-check.sh" 2>/dev/null; then
  echo "E2E FAIL: 场景A lint 未拦截"; exit 1
fi
rm bad.py
printf '%s' "$PUSH_JSON" | bash "$ROOT/scripts/pre-push-check.sh" 2>/dev/null \
  || { echo "E2E FAIL: 场景A lint 通过却被拦"; exit 1; }

# 3. 场景 B:代码变更未同步 state → Stop 警告
echo "print(1)" > ok.py
out=$(printf '{}' | bash "$ROOT/scripts/validate-state.sh")
printf '%s' "$out" | grep -q systemMessage || { echo "E2E FAIL: 场景B 无警告"; exit 1; }

# 4. 场景 C:gate 清单存在且被技能引用
for n in 1 2 3 4 5; do
  [ -f "$ROOT/templates/gate-checklists/phase$n-gate.md" ] || { echo "E2E FAIL: 缺 phase$n 清单"; exit 1; }
done
grep -q "phase1-gate.md" "$ROOT/skills/phase1-requirements/SKILL.md" || { echo "E2E FAIL: 技能未引用清单"; exit 1; }
grep -q "gate-checker" "$ROOT/skills/gate-check/SKILL.md" || { echo "E2E FAIL: gate-check 未引用子代理"; exit 1; }

echo "E2E PASS(scratch: $SCRATCH)"
