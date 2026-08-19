#!/usr/bin/env bash
cd "$(dirname "$0")/.."
ROOT="$PWD"
SB="$ROOT/scripts"
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
fail=0

mkrepo() {  # 在 $1 建 git 夹具(profile 自带可控假 lint 并提交,保证工作区干净)
  mkdir -p "$1" && cd "$1"
  git init -q && git config user.email t@t && git config user.name t
  cat > stack-profile.yaml <<'EOF'
project:
  name: "hook-fixture"
  type: "夹具"
stack:
  language: python
  lint_cmd: "bash -c '! grep -l FAILMARKER {changed_files}'"
  test_cmd: "true"
security:
  protected_paths: ["migrations/", ".env"]
budget:
  concurrent_max: 2
EOF
  git add -A && git commit -qm init
}

PUSH_JSON='{"tool_name":"Bash","tool_input":{"command":"git push origin test"}}'
OTHER_JSON='{"tool_name":"Bash","tool_input":{"command":"git status"}}'

# --- 用例1:非 push 命令 → exit 0 ---
mkrepo "$FIX/r1"
printf '%s' "$OTHER_JSON" | bash "$SB/pre-push-check.sh" || { echo "FAIL 用例1"; fail=1; }

# --- 用例2:lint 失败 → exit 2 阻断 ---
mkrepo "$FIX/r2"
echo "FAILMARKER" > bad.py   # 未提交,porcelain 可见
err_out=$(printf '%s' "$PUSH_JSON" | bash "$SB/pre-push-check.sh" 2>&1 >/dev/null)
[ "$?" -eq 2 ] || { echo "FAIL 用例2: 应 exit 2"; fail=1; }
printf '%s' "$err_out" | grep -q "lint 未通过" || { echo "FAIL 用例2: 阻断原因应为 lint 未通过,实际: $err_out"; fail=1; }

# --- 用例3:lint 通过 → exit 0 ---
rm bad.py
printf '%s' "$PUSH_JSON" | bash "$SB/pre-push-check.sh" 2>/dev/null || { echo "FAIL 用例3"; fail=1; }

cd "$ROOT"
# --- 用例4:代码变更+state未动 → 输出 systemMessage 警告 ---
mkrepo "$FIX/r4"
echo "print(1)" > ok.py
out=$(printf '{}' | bash "$SB/validate-state.sh")
printf '%s' "$out" | grep -q 'systemMessage' || { echo "FAIL 用例4: 应警告"; fail=1; }

# --- 用例5:backlog.md 同步变更 → 不警告 ---
echo "# backlog" > backlog.md
git add -A >/dev/null 2>&1   # 暂存也算"已纳入变更集"
echo "print(2)" >> ok.py
echo "update" >> backlog.md
out=$(printf '{}' | bash "$SB/validate-state.sh")
[ -z "$out" ] || { echo "FAIL 用例5: 不应警告,实际: $out"; fail=1; }

cd "$ROOT"
# --- 用例6:backlog+state → 摘要且 ≤40 行 ---
mkdir -p "$FIX/r6/.claude" && cd "$FIX/r6"
cat > backlog.md <<'EOF'
# demo 需求池
## In Progress
- ID-001 演示需求(Phase 1)
## Blocked
(空)
EOF
cat > .claude/state.json <<'EOF'
{"project":"demo","modules":{"m1":{"status":"in_progress","phase":"phase1_requirements"},"m2":{"status":"delivered","phase":"completed"}},"budget":{"concurrent_max":2,"currently_executing":1}}
EOF
out=$(bash "$SB/session-start.sh")
printf '%s\n' "$out" | grep -q 'In Progress\|进行中\|m1' || { echo "FAIL 用例6: 摘要缺内容"; fail=1; }
lines=$(printf '%s\n' "$out" | wc -l)
[ "$lines" -le 40 ] || { echo "FAIL 用例6: 超 40 行($lines)"; fail=1; }

# --- 用例7:空项目 → 提示 ai-init,exit 0 ---
mkdir -p "$FIX/r7" && cd "$FIX/r7"
out=$(bash "$SB/session-start.sh") || { echo "FAIL 用例7: 非零退出"; fail=1; }
printf '%s' "$out" | grep -q 'ai-init' || { echo "FAIL 用例7: 缺提示"; fail=1; }
cd "$ROOT"
# --- 用例8:命中 protected 路径 → permissionDecision: ask ---
cd "$FIX/r6"   # 复用:补一份带 protected_paths 的 profile
cp "$ROOT/tests/fixtures/stack-profile.yaml" stack-profile.yaml
WJSON='{"tool_name":"Write","tool_input":{"file_path":"migrations/001_init.py"}}'
out=$(printf '%s' "$WJSON" | bash "$SB/pre-write-protected.sh")
printf '%s' "$out" | grep -q '"permissionDecision": *"ask"\|permissionDecision.*ask' || { echo "FAIL 用例8: 应 ask,实际: $out"; fail=1; }

# --- 用例9:普通路径 → 无输出 exit 0 ---
WJSON2='{"tool_name":"Write","tool_input":{"file_path":"src/main.py"}}'
out=$(printf '%s' "$WJSON2" | bash "$SB/pre-write-protected.sh")
[ -z "$out" ] || { echo "FAIL 用例9: 应静默,实际: $out"; fail=1; }
cd "$ROOT"

[ "$fail" -eq 0 ] && echo "test_hooks PASS(all)"
exit "$fail"
