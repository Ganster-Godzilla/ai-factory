# AI Factory Plugin 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Odoo MES 验证过的 AI 协作架构抽象为技术栈中立的 Claude Code Plugin(skills×10 + hooks×4 + agents×3 + templates + scripts),任何新项目安装即用。

**Architecture:** 6+1 层(意图/流程/状态/记忆/工具/执行+监督,成长闭环横切);规则按 E0→E3 强制等级分级,成熟规则沿阶梯晋升;技术栈中立通过项目根 `stack-profile.yaml` 配置实现,hook/skill 只读配置不硬编码。

**Tech Stack:** Markdown(SKILL.md/agents/templates)、YAML(stack-profile)、JSON(plugin/hooks/state)、Bash(全部脚本,Git Bash 运行)、Python(hook 内 JSON/YAML 解析辅助,要求 `python` 在 PATH)。

**工作目录:** `d:\workspace\ai-factory`(以下所有相对路径基于此目录)

**Spec:** `docs/superpowers/specs/2026-07-25-ai-factory-plugin-design.md`

## Global Constraints

- **禁止 git**:ai-factory 目录不做版本管理。计划中**没有** commit 步骤;每个 Task 以"测试验证通过"作为完成标志
- **禁止** 修改 ai-factory 以外的任何项目文件(odoo18-e-manufacture / 3DWMS / quant-ai-trading)
- 所有 `.sh` 文件必须 **LF 行尾**(CRLF 会导致 Git Bash 执行失败);`tests/validate_plugin.sh` 内含 CRLF 检查
- 所有脚本在 **Windows Git Bash** 下可运行;`python`(非 python3)必须在 PATH
- hook 失败语义:**只有 pre-push-lint 是阻断级(exit 2)**;stop-state-sync 仅警告(systemMessage);pre-write-protected 为确认级(permissionDecision: ask);session-start 失败不得阻断会话
- stack-profile.yaml 缺失时,所有 hook **降级为不动作**,不得报错
- SKILL.md 遵循渐进披露:主文件 ≤200 行,清单/模板放 templates/ 按需引用
- SessionStart 注入 **≤40 行硬上限**

---

### Task 1: 插件骨架 + spec 修订 + 校验基架

**Files:**
- Modify: `docs/superpowers/specs/2026-07-25-ai-factory-plugin-design.md`(§六 补 `security.protected_paths` 字段——spec §七 引用了该字段但 §六 schema 漏定义,此处补齐)
- Create: `.claude-plugin/plugin.json`
- Create: `hooks/hooks.json`(先注册空结构,Task 3-6 逐个填入)
- Create: `tests/validate_plugin.sh`
- Create: `tests/run_all.sh`

**Interfaces:**
- Produces: `tests/validate_plugin.sh`(后续每个 Task 向其中追加检查项);`tests/run_all.sh`(统一入口,后续 Task 的测试脚本都挂进来)

- [ ] **Step 1: 修订 spec §六**

在 spec §六 的 `paths:` 之后、`budget:` 之前插入:

```yaml
security:
  protected_paths: []             # 写操作需确认的路径片段,如 ["migrations/", ".env"]
```

- [ ] **Step 2: 创建 plugin.json**

```json
{
  "name": "ai-factory",
  "version": "0.1.0",
  "description": "可复用 AI 工程架构:Phase 0-5 流程技能 + 状态机 + 规则强制分级(E0-E3) + 成长闭环。初始化: /ai-factory:ai-init"
}
```

- [ ] **Step 3: 创建 hooks/hooks.json(占位结构)**

```json
{
  "hooks": {
    "SessionStart": [],
    "PreToolUse": [],
    "Stop": []
  }
}
```

- [ ] **Step 4: 创建 tests/validate_plugin.sh**

```bash
#!/usr/bin/env bash
# validate_plugin.sh — 插件结构静态校验;新增产物在此追加检查
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOTW="$(cd "$(dirname "$0")/.." && pwd -W)"   # Windows 风格(d:/...),内嵌 python 代码必须用此值
fail=0
err() { echo "VALIDATE FAIL: $1"; fail=1; }

# 1. JSON 合法性
python -c "import json;d=json.load(open(r'$ROOTW/.claude-plugin/plugin.json',encoding='utf-8'));assert d.get('name')=='ai-factory'" \
  || err "plugin.json 非法"
python -c "import json;json.load(open(r'$ROOTW/hooks/hooks.json',encoding='utf-8'))" \
  || err "hooks.json 非法"

# 2. 无 CRLF(.sh 文件)
while IFS= read -r f; do
  if head -c 2000 "$f" | grep -q $'\r'; then err "CRLF 行尾: $f"; fi
done < <(find "$ROOT" -name '*.sh' -not -path '*/tmp/*')

# 3. SKILL.md 前置元数据(name + description)
for s in "$ROOT"/skills/*/SKILL.md; do
  [ -e "$s" ] || continue
  head -5 "$s" | grep -q '^name:' || err "$s 缺 name"
  head -5 "$s" | grep -q '^description:' || err "$s 缺 description"
done

# 4. agents 前置元数据
for a in "$ROOT"/agents/*.md; do
  [ -e "$a" ] || continue
  head -6 "$a" | grep -q '^name:' || err "$a 缺 name"
  head -6 "$a" | grep -q '^tools:' || err "$a 缺 tools"
done

# 5. hooks.json 引用的脚本存在
for p in $(python -c "
import json
d=json.load(open(r'$ROOTW/hooks/hooks.json',encoding='utf-8'))
for ev,entries in d.get('hooks',{}).items():
    for e in entries:
        for h in e.get('hooks',[]):
            cmd=h.get('command','')
            if 'CLAUDE_PLUGIN_ROOT' in cmd:
                print(cmd.split('CLAUDE_PLUGIN_ROOT}/')[-1])
"); do
  [ -f "$ROOT/$p" ] || err "hooks.json 引用缺失脚本: $p"
done

[ "$fail" -eq 0 ] && echo "VALIDATE PASS"
exit "$fail"
```

- [ ] **Step 5: 创建 tests/run_all.sh**

```bash
#!/usr/bin/env bash
# run_all.sh — 全部测试入口
cd "$(dirname "$0")/.."
pass=0; failed=0
for t in tests/validate_plugin.sh tests/test_profile.sh tests/test_hooks.sh tests/test_init.sh; do
  [ -f "$t" ] || continue
  if bash "$t"; then pass=$((pass+1)); else failed=$((failed+1)); echo ">>> FAILED: $t"; fi
done
echo "=============================="
echo "PASS: $pass  FAIL: $failed"
[ "$failed" -eq 0 ]
```

- [ ] **Step 6: 运行验证**

Run: `bash tests/run_all.sh`
Expected: `VALIDATE PASS`,PASS≥1 FAIL=0(test_profile/test_hooks/test_init 尚不存在,被跳过)

---

### Task 2: profile.sh 解析库

**Files:**
- Create: `scripts/lib/profile.sh`
- Create: `tests/fixtures/stack-profile.yaml`
- Test: `tests/test_profile.sh`

**Interfaces:**
- Produces(后续 Task 3/4/5/6/9 依赖):
  - `profile_get <file> <section.key>` → stdout 标量值;文件缺失返回 1;值为空/null 输出空
  - `profile_array <file> <section.key>` → stdout 空格分隔列表(解析行内数组 `[a, b]`)

- [ ] **Step 1: 写失败测试 tests/fixtures/stack-profile.yaml**

```yaml
project:
  name: "fixture-demo"
  type: "测试夹具"
stack:
  language: python
  lint_cmd: "python -m pyflakes {changed_files}"
  test_cmd: "pytest tests/"
  typecheck_cmd: null
vcs:
  branch_model: "feature→main"
  protected_branches: [main, test]
ci:
  type: none
  trigger_ref: ""
paths:
  requirements: "document/business"
  specs: "docs/superpowers/specs"
security:
  protected_paths: ["migrations/", ".env"]
budget:
  concurrent_max: 2
```

- [ ] **Step 2: 写失败测试 tests/test_profile.sh**

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
source scripts/lib/profile.sh
F=tests/fixtures/stack-profile.yaml
fail=0
chk() { [ "$2" = "$3" ] || { echo "FAIL: $1 期望[$3] 实际[$2]"; fail=1; }; }

chk "language"      "$(profile_get $F stack.language)"        "python"
chk "lint_cmd"      "$(profile_get $F stack.lint_cmd)"        "python -m pyflakes {changed_files}"
chk "typecheck空"   "$(profile_get $F stack.typecheck_cmd)"   ""
chk "branch_model"  "$(profile_get $F vcs.branch_model)"      "feature→main"
chk "concurrent"    "$(profile_get $F budget.concurrent_max)" "2"
chk "array"         "$(profile_array $F vcs.protected_branches)" "main test"
chk "protected"     "$(profile_array $F security.protected_paths)" "migrations/ .env"
profile_get /nonexistent.yaml stack.language >/dev/null 2>&1 && { echo "FAIL: 缺文件应返回非0"; fail=1; }

[ "$fail" -eq 0 ] && echo "test_profile PASS"
exit "$fail"
```

- [ ] **Step 3: 运行确认失败**

Run: `bash tests/test_profile.sh`
Expected: FAIL(profile.sh 不存在,source 报错)

- [ ] **Step 4: 实现 scripts/lib/profile.sh**

```bash
#!/usr/bin/env bash
# profile.sh — 解析 stack-profile.yaml(扁平二级 YAML,值含中文/空格/冒号均可)
# 用法: source 本文件后调用 profile_get / profile_array(需要 python 在 PATH)

profile_get() {
  local file="$1" path="$2"
  [ -f "$file" ] || return 1
  python - "$file" "$path" <<'PY'
import sys, re
file, path = sys.argv[1], sys.argv[2]
sec, key = path.split(".", 1)
cur = None
for line in open(file, encoding="utf-8"):
    if re.match(r"^[A-Za-z_][\w]*:", line):
        cur = line.split(":", 1)[0].strip()
        continue
    m = re.match(r"^\s+([A-Za-z_][\w]*):\s*(.*?)\s*$", line)
    if m and cur == sec and m.group(1) == key:
        v = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("\"'")
        if v and v != "null":
            print(v)
        break
PY
}

profile_array() {
  local raw
  raw=$(profile_get "$1" "$2") || return 1
  raw="${raw#[}"; raw="${raw%]}"
  printf '%s' "$raw" | tr ',' ' ' | tr -s ' ' | sed 's/^ //; s/ $//'
}
```

- [ ] **Step 5: 运行确认通过**

Run: `bash tests/run_all.sh`
Expected: `test_profile PASS` + `VALIDATE PASS`,FAIL=0

---

### Task 3: pre-push-check.sh(E3 阻断级 hook)

**Files:**
- Create: `scripts/pre-push-check.sh`
- Modify: `hooks/hooks.json`(PreToolUse 填入 Bash 条目)
- Test: `tests/test_hooks.sh`(本 Task 创建,后续 Task 4/5/6 向其中追加用例)

**Interfaces:**
- Consumes: `profile_get`(Task 2)
- Produces: hook 输入协议——stdin 收 PreToolUse JSON,`git push` 且 lint 失败时 **exit 2** + stderr 说明;其余 exit 0

- [ ] **Step 1: 写失败测试 tests/test_hooks.sh(首批 3 个用例)**

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
ROOT="$PWD"
SB="$ROOT/scripts"
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
fail=0

mkrepo() {  # 在 $1 建 git 夹具
  mkdir -p "$1" && cd "$1"
  git init -q && git config user.email t@t && git config user.name t
  cp "$ROOT/tests/fixtures/stack-profile.yaml" stack-profile.yaml
}

PUSH_JSON='{"tool_name":"Bash","tool_input":{"command":"git push origin test"}}'
OTHER_JSON='{"tool_name":"Bash","tool_input":{"command":"git status"}}'

# --- 用例1:非 push 命令 → exit 0 ---
mkrepo "$FIX/r1"
printf '%s' "$OTHER_JSON" | bash "$SB/pre-push-check.sh" || { echo "FAIL 用例1"; fail=1; }

# --- 用例2:lint 失败 → exit 2 阻断 ---
mkrepo "$FIX/r2"
# 夹具 lint 换成可控假 lint:含 FAILMARKER 则失败
sed -i 's|lint_cmd: .*|lint_cmd: "bash -c '"'"'! grep -l FAILMARKER {changed_files}'"'"'"|' stack-profile.yaml
echo "FAILMARKER" > bad.py   # 未提交,porcelain 可见
printf '%s' "$PUSH_JSON" | bash "$SB/pre-push-check.sh" 2>/dev/null
[ "$?" -eq 2 ] || { echo "FAIL 用例2: 应 exit 2"; fail=1; }

# --- 用例3:lint 通过 → exit 0 ---
rm bad.py
printf '%s' "$PUSH_JSON" | bash "$SB/pre-push-check.sh" 2>/dev/null || { echo "FAIL 用例3"; fail=1; }

cd "$ROOT"
[ "$fail" -eq 0 ] && echo "test_hooks PASS(pre-push)"
exit "$fail"
```

- [ ] **Step 2: 运行确认失败**

Run: `bash tests/test_hooks.sh`
Expected: 用例1 即失败(脚本不存在)

- [ ] **Step 3: 实现 scripts/pre-push-check.sh**

```bash
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
for f in $changed; do [ -f "$f" ] && files="$files $f"; done
[ -z "$files" ] && exit 0

run_cmd="${lint_cmd//\{changed_files\}/$files}"
if ! eval "$run_cmd" >&2; then
  echo "ai-factory[pre-push-lint]: lint 未通过,push 已阻断。修复后重试。命令: $run_cmd" >&2
  exit 2
fi
exit 0
```

- [ ] **Step 4: 注册到 hooks/hooks.json(替换 PreToolUse 空数组)**

```json
{
  "hooks": {
    "SessionStart": [],
    "PreToolUse": [
      {
        "matcher": "^Bash$",
        "hooks": [
          { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/pre-push-check.sh" }
        ]
      }
    ],
    "Stop": []
  }
}
```

- [ ] **Step 5: 运行确认通过**

Run: `bash tests/run_all.sh`
Expected: `test_hooks PASS(pre-push)` + VALIDATE PASS(hooks.json 引用脚本已存在)

---

### Task 4: validate-state.sh(Stop 警告级 hook)

**Files:**
- Create: `scripts/validate-state.sh`
- Modify: `hooks/hooks.json`(Stop 填入)
- Test: `tests/test_hooks.sh`(追加 2 个用例)

**Interfaces:**
- Consumes: 无(独立);Produces: Stop hook——工作区有代码变更且 backlog.md/state.json 均未变 → stdout 输出 `{"systemMessage": "..."}`;其余无输出 exit 0

- [ ] **Step 1: 追加失败测试用例(插到 test_hooks.sh 末尾的 `[ "$fail" -eq 0 ]` 行之前)**

```bash
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
```

并把末尾通过语改为 `echo "test_hooks PASS(pre-push + state)"`。

- [ ] **Step 2: 运行确认失败**

Run: `bash tests/test_hooks.sh`
Expected: 用例4 失败(脚本不存在)

- [ ] **Step 3: 实现 scripts/validate-state.sh**

```bash
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
  python -c "import json;print(json.dumps({'systemMessage':'⚠️ ai-factory: 检测到代码变更,但 backlog.md / state.json 未同步。结束会话前请运行 /ai-factory:backlog-sync 回写进度。'},ensure_ascii=False))"
fi
exit 0
```

- [ ] **Step 4: 注册 Stop hook(hooks.json)**

Stop 数组替换为:

```json
"Stop": [
  {
    "hooks": [
      { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/validate-state.sh" }
    ]
  }
]
```

- [ ] **Step 5: 运行确认通过**

Run: `bash tests/run_all.sh`
Expected: `test_hooks PASS(pre-push + state)`,FAIL=0

---

### Task 5: session-start.sh(会话启动注入 hook)

**Files:**
- Create: `scripts/session-start.sh`
- Modify: `hooks/hooks.json`(SessionStart 填入)
- Test: `tests/test_hooks.sh`(追加 2 个用例)

**Interfaces:**
- Produces: SessionStart hook——存在 backlog.md / .claude/state.json 时 stdout 输出 ≤40 行摘要;都不存在时输出 ai-init 提示;永不非零退出

- [ ] **Step 1: 追加失败测试用例(插到 test_hooks.sh 末尾的 `[ "$fail" -eq 0 ]` 行之前)**

```bash
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
```

通过语改为 `echo "test_hooks PASS(pre-push + state + session)"`。

- [ ] **Step 2: 运行确认失败**

Run: `bash tests/test_hooks.sh` → Expected: 用例6 失败

- [ ] **Step 3: 实现 scripts/session-start.sh**

```bash
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
import json
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
```

- [ ] **Step 4: 注册 SessionStart hook(hooks.json)**

SessionStart 数组替换为:

```json
"SessionStart": [
  {
    "matcher": "startup|resume",
    "hooks": [
      { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/session-start.sh" }
    ]
  }
]
```

- [ ] **Step 5: 运行确认通过**

Run: `bash tests/run_all.sh`
Expected: 全部 PASS,FAIL=0

---

### Task 6: pre-write-protected.sh(确认级 hook)

**Files:**
- Create: `scripts/pre-write-protected.sh`
- Modify: `hooks/hooks.json`(PreToolUse 追加 Write|Edit 条目)
- Test: `tests/test_hooks.sh`(追加 2 个用例)

**Interfaces:**
- Consumes: `profile_array <profile> security.protected_paths`(Task 2)
- Produces: PreToolUse(Write/Edit)——file_path 命中 protected_paths 任一片段 → 输出 `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask",...}}`;否则 exit 0 无输出

- [ ] **Step 1: 追加失败测试用例(插到 test_hooks.sh 末尾的 `[ "$fail" -eq 0 ]` 行之前)**

```bash
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
```

通过语改为 `echo "test_hooks PASS(all)"`。

- [ ] **Step 2: 运行确认失败**

Run: `bash tests/test_hooks.sh` → Expected: 用例8 失败

- [ ] **Step 3: 实现 scripts/pre-write-protected.sh**

```bash
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
      python -c "import json,sys;print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'ask','permissionDecisionReason':'ai-factory: 命中保护路径 %s — 请确认写入必要性' % sys.argv[1]}},ensure_ascii=False))" "$pat"
      exit 0
      ;;
  esac
done
exit 0
```

- [ ] **Step 4: 注册(PreToolUse 数组追加,注意 JSON 逗号)**

```json
,
      {
        "matcher": "^Write$|^Edit$",
        "hooks": [
          { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/scripts/pre-write-protected.sh" }
        ]
      }
```

- [ ] **Step 5: 运行确认通过**

Run: `bash tests/run_all.sh`
Expected: `test_hooks PASS(all)` + VALIDATE PASS,FAIL=0

---

### Task 7: 模板批(9 个模板文件)

**Files:**
- Create: `templates/stack-profile.yaml`
- Create: `templates/claude-md.template.md`
- Create: `templates/backlog.template.md`
- Create: `templates/state.template.json`
- Create: `templates/memory-index.template.md`
- Create: `templates/rules-registry.md`
- Create: `templates/proposal.template.md`
- Create: `templates/prd.template.md`
- Create: `templates/design.template.md`
- Test: `tests/validate_plugin.sh`(追加模板检查)

**Interfaces:**
- Produces(Task 9 init-project.sh 依赖):上述文件名 + 占位符集合 `{{PROJECT_NAME}} {{PROJECT_TYPE}} {{LANGUAGE}} {{LINT_CMD}} {{TEST_CMD}}`
- Produces(Task 10/11 skills 引用):`templates/proposal.template.md`、`templates/prd.template.md`、`templates/design.template.md`

- [ ] **Step 1: templates/stack-profile.yaml**

```yaml
project:
  name: "{{PROJECT_NAME}}"
  type: "{{PROJECT_TYPE}}"
stack:
  language: {{LANGUAGE}}
  lint_cmd: "{{LINT_CMD}}"
  test_cmd: "{{TEST_CMD}}"
  typecheck_cmd: null
vcs:
  branch_model: "feature→main"
  protected_branches: [main]
ci:
  type: none
  trigger_ref: ""
paths:
  requirements: "document/business"
  specs: "docs/superpowers/specs"
security:
  protected_paths: []
budget:
  concurrent_max: 2
```

- [ ] **Step 2: templates/claude-md.template.md**

```markdown
# {{PROJECT_NAME}} — Claude Code 入口

## 每次会话
1. 读本文件与 backlog.md(In Progress/Blocked)
2. 任务分型:新需求 → /ai-factory:phase0-proposal;修订/缺陷 → 直接走 docs/superpowers/specs/
3. 任何"推进/下一阶段"请求 → /ai-factory:gate-check(刚性)

## 项目信息
- 类型: {{PROJECT_TYPE}}
- 技术栈/CI: 见 stack-profile.yaml
- 状态机: .claude/state.json;规则登记: .claude/rules-registry.md

## 刚性规则
- Proposal 只是 Phase 0 动议,不等于 PRD/设计文档
- Phase 产物不齐,禁止进入下一阶段
- 任务完成必须回写 backlog.md + state.json(/ai-factory:backlog-sync)
- 犯错后执行 /ai-factory:mistake-retro
```

- [ ] **Step 3: templates/backlog.template.md**

```markdown
# {{PROJECT_NAME}} 需求池 / 进度看板

> 会话启动读取;任务完成时更新(/ai-factory:backlog-sync)。

## In Progress
(空)

## Blocked
(空)

## Done
(空)

## 关键决策
| 日期 | 决策 | 理由 |
|---|---|---|

## 下一步
(空)
```

- [ ] **Step 4: templates/state.template.json**

```json
{
  "project": "{{PROJECT_NAME}}",
  "version": "1.0",
  "last_updated": "",
  "overview": { "description": "{{PROJECT_TYPE}}", "status": "active", "active_modules": [] },
  "modules": {},
  "budget": { "concurrent_max": 2, "currently_executing": 0 },
  "pending_notifications": []
}
```

- [ ] **Step 5: templates/memory-index.template.md**

```markdown
# {{PROJECT_NAME}} 项目记忆索引

## Feedback(工作方式纠正)
## Project(进展与决策)
## Reference(外部资源)
```

- [ ] **Step 6: templates/rules-registry.md**

```markdown
# 规则登记表(Rules Registry)

> 等级:E0 文档约定 / E1 提示注入 / E2 脚本校验 / E3 Hook 强制。
> 晋升触发:同一 E1 规则被违反 2 次 → 必须晋升 E2/E3(/ai-factory:mistake-retro 执行)。

| 规则 | 等级 | 载体 | 录入日期 | 晋升历史 |
|---|---|---|---|---|
| push 前跑 lint | E3 | hook: pre-push-check.sh | init | — |
| 代码变更需同步 backlog/state | E3(警告) | hook: validate-state.sh | init | — |
| 会话启动注入 backlog 摘要 | E3(注入) | hook: session-start.sh | init | — |
| 保护路径写入需确认 | E3(确认) | hook: pre-write-protected.sh | init | — |
| Phase 门禁刚性 | E1 | skill: gate-check | init | — |
```

- [ ] **Step 7: templates/proposal.template.md**

```markdown
# PROJ-<日期>-<序号>: <标题>

> Phase 0 原始动议——只写以下四项。详细论证归 PRD,实现方案归设计文档。

- **日期**: YYYY-MM-DD
- **状态**: speculative | candidate | accepted | executing | suspended | obsolete | archived
- **Backlog ID**: (登记后回填)

## 问题/机会

## 建议方向

## 粗略范围

## 不做什么
```

- [ ] **Step 8: templates/prd.template.md**

```markdown
# PRD-<id>: <标题>

> Phase 1 产物。门禁:templates/gate-checklists/phase1-gate.md

## Why(问题与价值)

## What(范围与边界)

## 功能清单
| # | 功能 | 优先级 | 验收标准 |
|---|---|---|---|

## 非功能需求

## 验收标准

## 歧义与开放问题
→ 逐条登记到 歧义澄清记录.md
```

- [ ] **Step 9: templates/design.template.md**

```markdown
# 技术方案: <标题>

> Phase 2 产物。门禁:templates/gate-checklists/phase2-gate.md

## Architecture(结构与边界)

## How(关键实现)

## 数据设计

## 接口契约

## Checkpoints(验证点)

## Rollback(回滚方案)

## 测试用例设计映射
```

- [ ] **Step 10: 追加模板检查到 tests/validate_plugin.sh(`[ "$fail" -eq 0 ]` 之前插入)**

```bash
# 6. 模板存在性与合法性
for t in stack-profile.yaml claude-md.template.md backlog.template.md state.template.json \
         memory-index.template.md rules-registry.md proposal.template.md prd.template.md design.template.md; do
  [ -f "$ROOT/templates/$t" ] || err "缺模板: $t"
done
python -c "import json;json.load(open(r'$ROOT/templates/state.template.json',encoding='utf-8'))" \
  || err "state.template.json 非法"
```

注意:state.template.json 含 `{{PROJECT_NAME}}` 占位符——仍是合法 JSON(占位符在字符串值内),该校验可通过。

- [ ] **Step 11: 运行验证**

Run: `bash tests/run_all.sh`
Expected: VALIDATE PASS,FAIL=0

---

### Task 8: 门禁清单(5 张)

**Files:**
- Create: `templates/gate-checklists/phase1-gate.md` ~ `phase5-gate.md`
- Test: `tests/validate_plugin.sh`(追加清单检查)

**Interfaces:**
- Produces(Task 10/11 引用):`templates/gate-checklists/phase{1..5}-gate.md`

- [ ] **Step 1: phase1-gate.md**

```markdown
# Phase 1 门禁检查清单(需求分析)

- [ ] PRD.md 存在,含 Why / What / 非功能需求 / 验收标准,各节非空
- [ ] 功能清单.md 存在,条目带优先级
- [ ] 歧义澄清记录.md 存在(无歧义也需显式说明)
- [ ] backlog.md 已登记本需求 ID 与状态
- [ ] state.json 本模块 phase=phase1_requirements 且 milestones.phase1_requirements=completed(通过后置)
```

- [ ] **Step 2: phase2-gate.md**

```markdown
# Phase 2 门禁检查清单(方案设计)

- [ ] 技术方案.md 存在,含 Architecture / How / Checkpoints / Rollback,各节非空
- [ ] 涉及 schema 变更 → 数据库设计.md 存在
- [ ] 涉及对外接口 → 接口文档.md 存在
- [ ] 测试用例设计覆盖 PRD 全部验收标准(逐条映射)
- [ ] 设计经用户逐节确认(无未决开放问题)
- [ ] state.json milestones.phase2_design=completed(通过后置)
```

- [ ] **Step 3: phase3-gate.md**

```markdown
# Phase 3 门禁检查清单(TDD 实现)

- [ ] 每个功能点有"先失败后通过"的测试记录(TDD 痕迹)
- [ ] stack-profile lint_cmd 通过
- [ ] stack-profile test_cmd 全绿(核对执行用例数非 0,防静默跳过)
- [ ] 代码评审完成(superpowers:requesting-code-review)
- [ ] 评审意见全部处理或显式拒绝并记录理由
- [ ] state.json milestones.phase3_implementation=completed(通过后置)
```

- [ ] **Step 4: phase4-gate.md**

```markdown
# Phase 4 门禁检查清单(测试验证)

- [ ] 测试报告存在(环境 / 范围 / 用例结果 / 缺陷清单 / 结论)
- [ ] 黑盒验证记录存在(验证人 + 日期)
- [ ] 遗留缺陷全部登记 backlog(禁止口头遗留)
- [ ] state.json milestones.phase4_testing=completed(通过后置)
```

- [ ] **Step 5: phase5-gate.md**

```markdown
# Phase 5 门禁检查清单(部署发布)

- [ ] 按 stack-profile vcs.branch_model 完成合并
- [ ] 部署记录存在(环境 / 版本 / 时间 / 构建号)
- [ ] 回滚方案明确且可执行
- [ ] 目标环境冒烟验证通过
- [ ] backlog.md 状态更新为 delivered
- [ ] state.json phase=completed(通过后置)
```

- [ ] **Step 6: 追加检查到 validate_plugin.sh(模板检查块之后)**

```bash
# 7. 门禁清单
for n in 1 2 3 4 5; do
  [ -f "$ROOT/templates/gate-checklists/phase$n-gate.md" ] || err "缺门禁清单 phase$n"
done
```

- [ ] **Step 7: 运行验证**

Run: `bash tests/run_all.sh` → Expected: VALIDATE PASS,FAIL=0

---

### Task 9: init-project.sh + ai-init 技能

**Files:**
- Create: `scripts/init-project.sh`
- Create: `skills/ai-init/SKILL.md`
- Test: `tests/test_init.sh`

**Interfaces:**
- Consumes: Task 7 模板 + 占位符集合
- Produces: `init-project.sh --dir D --name N --type T --language L [--lint-cmd C] [--test-cmd C]`;生成 CLAUDE.md / backlog.md / .claude/state.json / .claude/memory/MEMORY.md / .claude/rules-registry.md / stack-profile.yaml / docs 目录树

- [ ] **Step 1: 写失败测试 tests/test_init.sh**

```bash
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

[ "$fail" -eq 0 ] && echo "test_init PASS"
exit "$fail"
```

- [ ] **Step 2: 运行确认失败**

Run: `bash tests/test_init.sh` → Expected: FAIL(脚本不存在)

- [ ] **Step 3: 实现 scripts/init-project.sh**

```bash
#!/usr/bin/env bash
# init-project.sh — 在目标目录生成 AI Factory 骨架
set -e
DIR="."; NAME=""; PTYPE=""; LANG="python"; LINT=""; TESTC=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2;;
    --name) NAME="$2"; shift 2;;
    --type) PTYPE="$2"; shift 2;;
    --language) LANG="$2"; shift 2;;
    --lint-cmd) LINT="$2"; shift 2;;
    --test-cmd) TESTC="$2"; shift 2;;
    *) echo "未知参数: $1" >&2; exit 1;;
  esac
done
[ -z "$NAME" ] && { echo "缺少 --name" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$DIR/.claude/memory" "$DIR/docs/superpowers/specs" "$DIR/docs/superpowers/plans"

render() {  # render <模板名> <输出相对路径>
  sed -e "s|{{PROJECT_NAME}}|$NAME|g" \
      -e "s|{{PROJECT_TYPE}}|$PTYPE|g" \
      -e "s|{{LANGUAGE}}|$LANG|g" \
      -e "s|{{LINT_CMD}}|$LINT|g" \
      -e "s|{{TEST_CMD}}|$TESTC|g" \
      "$ROOT/templates/$1" > "$DIR/$2"
}

render claude-md.template.md CLAUDE.md
render backlog.template.md backlog.md
render state.template.json .claude/state.json
render stack-profile.yaml stack-profile.yaml
render memory-index.template.md .claude/memory/MEMORY.md
render rules-registry.md .claude/rules-registry.md

echo "ai-factory 骨架已生成于 $DIR"
echo "下一步:审阅 stack-profile.yaml,然后阅读 CLAUDE.md"
```

- [ ] **Step 4: 创建 skills/ai-init/SKILL.md**

```markdown
---
name: ai-init
description: 初始化新项目的 AI Factory 骨架(CLAUDE.md / backlog / state / memory / stack-profile)。当用户说"初始化项目""套用 AI 架构""setup 新项目""接入 ai-factory"时使用。
---

# AI Init — 项目骨架初始化

## 流程

1. 询问并逐项确认(用 AskUserQuestion,多选合并提问):
   - 项目名称、一句话简述
   - 主语言(python / typescript / 其他)
   - lint 命令(须含 `{changed_files}` 占位符;没有则留空)
   - 测试命令
   - CI 类型(jenkins / github / none)与分支模型(feature→main / feature→test / trunk)
2. 执行初始化(当前目录即项目根):
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/scripts/init-project.sh --dir . \
     --name "<名>" --type "<简述>" --language "<语言>" \
     --lint-cmd "<lint命令>" --test-cmd "<测试命令>"
   ```
3. 按第 1 步答案手工补全 stack-profile.yaml 的 `ci.type` 与 `vcs.branch_model`
4. 展示产物清单,请用户审阅 stack-profile.yaml
5. 告知采用级别:L1(phase skills)立即可用;hooks 随插件启用即 L2

## 规则

- 已存在 CLAUDE.md → **不覆盖**,改为追加 "## AI Factory" 章节并保留原内容
- 已存在 backlog.md / state.json → 提示冲突,由用户决定是否备份后重建
- **不执行 git init**(是否纳入版本管理由用户决定)
```

- [ ] **Step 5: 运行确认通过**

Run: `bash tests/run_all.sh`
Expected: `test_init PASS` + VALIDATE PASS,FAIL=0

---

### Task 10: Phase 技能 ×6(流程层主体)

**Files:**
- Create: `skills/phase0-proposal/SKILL.md`
- Create: `skills/phase1-requirements/SKILL.md`
- Create: `skills/phase2-design/SKILL.md`
- Create: `skills/phase3-implement/SKILL.md`
- Create: `skills/phase4-verify/SKILL.md`
- Create: `skills/phase5-release/SKILL.md`

**Interfaces:**
- Consumes: `templates/gate-checklists/phase{1..5}-gate.md`(Task 8)、`templates/proposal.template.md` 等(Task 7)
- Produces: 技能名 `phase0-proposal` … `phase5-release`(Task 11 的 gate-check 与 CLAUDE.md 路由引用)

- [ ] **Step 1: phase0-proposal/SKILL.md**

```markdown
---
name: phase0-proposal
description: Phase 0 提案阶段。当用户提出新想法/新需求/新模块("我有个想法""新需求""做个XX")时使用,产出 Proposal 文档。Proposal 只是原始动议,不是 PRD 或设计文档。
---

# Phase 0 — Proposal(原始动议)

## 产物
`.claude/proposals/PROJ-{YYYYMMDD}-{seq}.md`(seq 当日递增)
模板:`${CLAUDE_PLUGIN_ROOT}/templates/proposal.template.md`

## 内容边界(只写四项)
1. 问题/机会  2. 建议方向  3. 粗略范围  4. 不做什么

## 禁止
- ❌ 写 Why/What 详细论证(那是 Phase 1 PRD)
- ❌ 写 Architecture/How(那是 Phase 2 设计)
- ❌ 未登记 backlog 就启动后续工作
- ❌ 把 proposal 讨论结论直接当成 Phase 1 完成

## 下一步
用户确认 proposal → 登记 backlog.md(新行,状态: proposal)→ 引导进入 /ai-factory:phase1-requirements
```

- [ ] **Step 2: phase1-requirements/SKILL.md**

```markdown
---
name: phase1-requirements
description: Phase 1 需求分析。当用户要求写 PRD/功能清单/需求文档,或 proposal 已确认要进入需求分析时使用。
---

# Phase 1 — 需求分析

## 产物(根目录 = stack-profile paths.requirements/{模块}/01_需求分析/)
- PRD.md(Why / What / 非功能需求 / 验收标准)
- 功能清单.md(条目 + 优先级)
- 歧义澄清记录.md
模板:`${CLAUDE_PLUGIN_ROOT}/templates/prd.template.md`

## 流程
1. 读取对应 proposal 与 backlog 登记行
2. 逐节产出,每节与用户确认后再写下一节
3. 歧义点当场澄清并登记 歧义澄清记录.md

## 门禁(刚性)
完成后调 /ai-factory:gate-check(phase1),清单:`${CLAUDE_PLUGIN_ROOT}/templates/gate-checklists/phase1-gate.md`
产物不齐 → 禁止进入 Phase 2,列出缺失项请用户补齐

## 收尾
更新 state.json(phase/milestones)+ backlog 状态 → /ai-factory:backlog-sync
```

- [ ] **Step 3: phase2-design/SKILL.md**

```markdown
---
name: phase2-design
description: Phase 2 方案设计。Phase 1 门禁通过后,或修订/缺陷修复需要设计 spec 时使用。
---

# Phase 2 — 方案设计

## 任务分型(先判断,路径不同)
- **新需求** → 正式技术方案:`paths.requirements/{模块}/02_设计文档/技术方案.md`
- **修订/缺陷**(不改系统边界)→ spec:`paths.specs/YYYY-MM-DD-<topic>-design.md`
- 冲突时一律优先项目规范路径,不用 skill 默认路径

## 产物
技术方案.md 六节齐全:Architecture / How / 数据设计 / 接口契约 / Checkpoints / Rollback
模板:`${CLAUDE_PLUGIN_ROOT}/templates/design.template.md`

## 流程
1. 先调 superpowers:brainstorming 探明意图、约束与取舍(禁止直接写方案)
2. 设计分节呈现,逐节确认

## 门禁(刚性)
调 /ai-factory:gate-check(phase2);不通过**禁止编码**
```

- [ ] **Step 4: phase3-implement/SKILL.md**

```markdown
---
name: phase3-implement
description: Phase 3 TDD 实现。设计门禁通过、进入编码时使用;强制测试先行。
---

# Phase 3 — TDD 实现

## 委托关系(不重复造轮子)
- 实现方法论 → superpowers:test-driven-development
- 计划执行 → superpowers:executing-plans 或 superpowers:subagent-driven-development
- 本技能只管**项目层约束**:

## 项目层约束
1. 编码前确认 state.json 中 Phase 2 门禁已过,否则退回 gate-check
2. 每个功能点:失败测试 → 最小实现 → 测试通过 → 重构
3. 提交前本地跑 stack-profile 的 lint_cmd 与 test_cmd(pre-push hook 兜底,但不该走到兜底)
4. 并行多任务 → 使用 worktree 隔离(superpowers:using-git-worktrees),禁止多任务混同一工作区
5. 全绿后核对测试执行数非 0(防静默跳过)

## 收尾
gate-check(phase3)→ backlog-sync
```

- [ ] **Step 5: phase4-verify/SKILL.md**

```markdown
---
name: phase4-verify
description: Phase 4 测试验证。实现完成进入系统测试/黑盒验证时使用。
---

# Phase 4 — 测试验证

## 产物
- 测试报告:环境 / 范围 / 用例结果 / 缺陷清单 / 结论
- 黑盒验证记录:验证人 + 日期 + 结论

## 规则
- 测试环境尽量贴近生产;记录环境差异
- **全绿 ≠ 实跑**:必须核对用例执行数,0 执行按失败处理
- 遗留缺陷逐条登记 backlog,禁止口头遗留
- 发现新问题且需改代码 → 回到 phase3-implement(小修)或 phase2-design(动边界)

## 门禁
gate-check(phase4)
```

- [ ] **Step 6: phase5-release/SKILL.md**

```markdown
---
name: phase5-release
description: Phase 5 部署发布。合并分支、部署、生产/目标环境验证、交付收尾时使用。
---

# Phase 5 — 部署发布

## 步骤
1. 按 stack-profile `vcs.branch_model` 合并(不询问,直接按模型执行)
2. 按 `ci.trigger_ref` 触发部署,监控构建至终态(成功/失败都要确认)
3. 目标环境冒烟验证
4. 确认回滚方案可执行

## 收尾
- backlog 状态 → delivered;state.json phase=completed
- 执行 /ai-factory:mistake-retro 复盘本周期(有无犯错、规则是否需晋升)
```

- [ ] **Step 7: 运行验证**

Run: `bash tests/run_all.sh`
Expected: VALIDATE PASS(6 个 SKILL.md 元数据齐全),FAIL=0

---

### Task 11: gate-check + backlog-sync + mistake-retro(机制技能 ×3)

**Files:**
- Create: `skills/gate-check/SKILL.md`
- Create: `skills/backlog-sync/SKILL.md`
- Create: `skills/mistake-retro/SKILL.md`

**Interfaces:**
- Consumes: Task 8 清单、Task 10 技能名、`templates/rules-registry.md`

- [ ] **Step 1: gate-check/SKILL.md**

```markdown
---
name: gate-check
description: Phase 门禁检查(刚性)。当用户说"推进""进入下一阶段""门禁检查""gate check"时必用;产物不齐时有权且必须拒绝推进。不可跳过。
---

# Gate Check — 刚性门禁

## 规则(不可协商)
1. 读 state.json 确定当前模块与目标 Phase
2. 读对应清单 `${CLAUDE_PLUGIN_ROOT}/templates/gate-checklists/phase{N}-gate.md`
3. **派发 ai-factory:gate-checker 子代理**在干净上下文逐项核查(避免自己查自己)
4. 输出逐项 ✅/❌ + 缺失项的具体路径
5. 存在任一 ❌ → **明确拒绝推进**,给出补齐路径。禁止"先推进后补票"
6. 用户要求跳过 → 引用本规则并拒绝;这是刚性门禁

## 全过后
- 更新 state.json:`milestones.<phaseN>=completed`、`phase` 推进、`last_updated`
- 更新 backlog.md 状态
- 告知用户可进入的下一 Phase 及对应技能名
```

- [ ] **Step 2: backlog-sync/SKILL.md**

```markdown
---
name: backlog-sync
description: 任务完成/会话收尾时回写 backlog.md 与 state.json(状态、进度、阻塞、关键决策、下一步)。
---

# Backlog Sync — 状态回写

## 触发
任务完成、Phase 切换、会话结束前(Stop hook 会警告未同步的情况)

## 步骤
1. 回顾本次实际变更(git status / git log,无 git 则回顾文件修改清单)
2. 更新 backlog.md:状态 / 进度 / 阻塞 / 关键决策(带日期)/ 下一步
3. 更新 state.json:phase / milestones / notes / last_updated(填当前 ISO 时间)
4. 若本次周期犯过错 → 顺带执行 /ai-factory:mistake-retro

## 纪律
- 状态写实际值,不写"应该"的值;阻塞要写明等什么、找谁
- backlog 同时是看板:In Progress 区条目数不应超过 budget.concurrent_max
```

- [ ] **Step 3: mistake-retro/SKILL.md**

```markdown
---
name: mistake-retro
description: 犯错后或定期复盘:根因入记忆、规则沿 E0→E3 阶梯机制化晋升、登记 rules-registry。当发现错误/返工/被用户纠正时使用。
---

# Mistake Retro — 成长闭环

## 五问流程
1. **根因是什么?** → 写入项目记忆(type: feedback,含 Why + How to apply)
2. **能否机制化?** → 能:产出 E2(检查脚本)或 E3(hook)草稿
3. **不能机制化的原因?** → 纯判断类规则,留 E1 并记录原因
4. **登记** `.claude/rules-registry.md`:规则 / 等级 / 载体 / 日期 / 晋升历史
5. **验证**:下次同类场景应零复发;跟踪并在再犯时升级处理

## 晋升触发(刚性)
同一条 E1 规则**被违反 2 次 → 必须晋升 E2/E3**,不允许继续靠自觉

## 可选
派发 ai-factory:mistake-auditor 子代理扫描近期变更,交叉验证是否还有未登记的返工模式
```

- [ ] **Step 4: 运行验证**

Run: `bash tests/run_all.sh` → Expected: VALIDATE PASS,FAIL=0

---

### Task 12: 子代理 ×3

**Files:**
- Create: `agents/gate-checker.md`
- Create: `agents/backlog-keeper.md`
- Create: `agents/mistake-auditor.md`

**Interfaces:**
- Consumes: 被 Task 11 skills 与 session-start hook 引用(名称须一致:`ai-factory:gate-checker` / `backlog-keeper` / `mistake-auditor`)

- [ ] **Step 1: agents/gate-checker.md**

```markdown
---
name: gate-checker
description: 只读门禁核查员。在干净上下文中对照 gate checklist 逐项核查产物存在性与完整性,输出 ✅/❌ 报告。供 gate-check 技能派发。
tools: Read, Glob, Grep
---

你是门禁核查员。只读,不修改任何文件,不带立场,不替主循环找台阶。

## 输入
模块名、目标 Phase、checklist 文件路径、state.json 路径、产物根目录

## 步骤
1. 读 checklist
2. 逐项核查:文件存在?必需章节非空?state.json 字段值符合?
3. 输出报告

## 输出格式
逐项 `✅` / `❌` + 缺失/不完整项的具体路径与原因 + 总结论(PASS / FAIL)

## 纪律
- 文件存在但必需章节为空 → ❌
- 无法确定 → ❌ 并注明"需人工判断"
```

- [ ] **Step 2: agents/backlog-keeper.md**

```markdown
---
name: backlog-keeper
description: 只读状态摘要员。解析 backlog.md / .claude/state.json / proposals,生成 ≤40 行会话启动摘要。供会话启动时调用。
tools: Read, Glob, Grep
---

你是状态摘要员。只读。

## 输出(≤40 行硬上限)
1. In Progress 模块:名称 / Phase / 阻塞原因
2. Blocked 清单(等什么、找谁)
3. 活跃 proposal(.claude/proposals/active/)
4. 并发预算用量(currently_executing / concurrent_max)
5. 建议今日焦点(基于 backlog 下一步)

## 纪律
文件缺失直接说明,不编造内容
```

- [ ] **Step 3: agents/mistake-auditor.md**

```markdown
---
name: mistake-auditor
description: 只读复盘审计员。扫描近期变更与返工痕迹,提议新记忆条目与规则晋升建议。供 mistake-retro 或定期复盘调用。
tools: Read, Glob, Grep, Bash
---

你是复盘审计员。只读(Bash 仅限 git log / git diff / git status)。

## 步骤
1. `git log --oneline -10` + `git diff --stat HEAD~3` 回顾近期变更(无 git 则跳过此步并说明)
2. 对照 .claude/rules-registry.md 现有规则
3. 识别:无对应规则的返工/修复模式(连续修同一文件、fix 提交链)
4. 形成提议

## 输出
逐条:根因假设 → 建议记忆草稿(type: feedback)→ 建议 E 等级 → 是否达晋升线(E1 违反≥2 次)

## 纪律
不直接写文件;提议交主循环确认后落盘
```

- [ ] **Step 4: 运行验证**

Run: `bash tests/run_all.sh` → Expected: VALIDATE PASS(agents 元数据检查通过),FAIL=0

---

### Task 13: 文档 ×3(architecture / adoption-guide / mes-migration-guide)

**Files:**
- Create: `docs/architecture.md`
- Create: `docs/adoption-guide.md`
- Create: `docs/mes-migration-guide.md`
- Test: `tests/validate_plugin.sh`(追加文档检查)

**Interfaces:**
- Consumes: 全部前序 Task 的实际产物名(文档引用必须与真实文件一致)

- [ ] **Step 1: docs/architecture.md**

```markdown
# AI Factory 架构说明

> 设计规格:docs/superpowers/specs/2026-07-25-ai-factory-plugin-design.md(权威,冲突时以规格为准)

## 6+1 层

| 层 | 产物 | 机制 |
|---|---|---|
| L0 意图 | templates/(proposal/PRD/design) | 人类拥有决策权 |
| L1 流程 | skills/(10 个,触发式加载) | 替代"记得去读" |
| L2 状态 | backlog.md + .claude/state.json | 机器可读、Stop hook 校验 |
| L3 记忆 | .claude/memory/ + mistake-retro | 错误→机制孵化 |
| L4 工具 | stack-profile.yaml + scripts/ | 技术栈中立配置点 |
| L5 执行 | 主循环 + agents/(只读) | 上下文隔离 |
| L6 监督 | hooks/(4 个) | 确定性强制 |
| 横切 | 成长闭环 E0→E3 | 规则只升不降 |

## 规则强制等级
E0 文档约定 / E1 提示注入 / E2 脚本校验 / E3 Hook 强制。
同一 E1 规则被违反 2 次 → 必须晋升。登记处:.claude/rules-registry.md。

## Hook 失败语义
| Hook | 级别 | 行为 |
|---|---|---|
| pre-push-check | 阻断(exit 2) | git push 前跑 lint_cmd |
| validate-state | 警告(systemMessage) | 代码变了 backlog/state 没变 |
| pre-write-protected | 确认(ask) | 命中 security.protected_paths |
| session-start | 注入(≤40 行) | backlog/state 摘要 |

## 安装
方式一(本地目录):在 ~/.claude/plugins/ 下创建指向本目录的链接/副本,settings.json 中 `enabledPlugins` 加 `"ai-factory@local": true`。
方式二(marketplace):打包发布到私有 marketplace 后 `claude plugin install ai-factory`。
启用后 hooks 自动生效;skills 以 `ai-factory:<名>` 调用。
```

- [ ] **Step 2: docs/adoption-guide.md**

```markdown
# 采用路径(L0→L3)

| 级别 | 内容 | 前置 |
|---|---|---|
| L0 骨架 | 装插件 → `/ai-factory:ai-init` → CLAUDE.md/backlog/state/profile | 10 分钟 |
| L1 流程 | phase0-5 + gate-check + backlog-sync 技能生效 | L0 |
| L2 强制 | 4 个 hooks 全开(装插件即生效,验证见下) | L0 |
| L3 自治 | 后台 agent + Monitor + Cron 唤醒规则 | L2 + 团队接受度 |

## 各项目建议起点
- 全新项目:L0 → L1 直接到位
- 已有流程的项目(如 Odoo MES):先 L0 并存,按 mes-migration-guide 渐进替换到 L2
- 成熟项目试点自治:L3(需先积累 rules-registry 数据)

## 启用后手工验证清单(LLM 行为项,脚本测不到)
- [ ] 新会话启动时看到 backlog 摘要注入(≤40 行)
- [ ] 说"进入下一阶段"且产物缺失 → 被 gate-check 拒绝
- [ ] 故意改一个代码文件后结束回合 → 收到 state 未同步警告
- [ ] git push 且 lint 失败 → 被阻断,stderr 显示阻断原因
- [ ] 写 protected_paths 内文件 → 弹出确认
```

- [ ] **Step 3: docs/mes-migration-guide.md**

```markdown
# Odoo MES 回灌指南(后续独立立项,本轮不执行)

> 目标:odoo18-e-manufacture 从"决策树+记忆纪律"迁移到 ai-factory L2。原则:**并存渐进,不搞大爆炸替换**。

## 一、决策树章节 → 技能映射

| 99-decision-tree.md 章节 | 去向 |
|---|---|
| 一、主决策树概览 | CLAUDE.md 路由(薄) |
| 二、会话启动层 | session-start hook + backlog-keeper |
| 三、任务接收层 | phase0-proposal |
| 四、需求资料收集层 | phase1-requirements |
| 五/六、Phase 1/2 | phase1-requirements / phase2-design |
| 七、Phase 3 TDD | phase3-implement |
| 八/附录 E、Phase 3.5/5 | phase5-release + jenkins MCP(ci.trigger_ref) |
| 九、完成收尾层 | backlog-sync |
| 附录 B、门禁清单 | templates/gate-checklists/(按 MES 产物定制副本) |
| 附录 D、单人执行保障 | backlog-sync + mistake-retro |

## 二、记忆 → E 等级映射(首批 20 条)

| 现有记忆 | 建议等级 | 机制化载体 |
|---|---|---|
| 推送前跑 pyflakes | E3 | pre-push-lint(lint_cmd=pyflakes) |
| git commit+push 习惯 | E1(保留) | backlog-sync 步骤 |
| Odoo 18 不用 attrs | E2 | 脚本:grep -r 'attrs=' fj_custom/*/views/ |
| create 必加 model_create_multi | E2 | 脚本:检测 @api.model create 缺装饰器 |
| 新模型必须同步 ACL | E2 | 脚本:新 models 行 vs ir.model.access.csv |
| --test-tags 正确写法 | E1 | phase4-verify 指令 |
| env.get 返回空 recordset | E1 | memory 保留(判断类) |
| OWL 模板无全局函数 | E2 | 脚本:grep encodeURIComponent 等于 .xml |
| OWL 禁 inline delete | E2 | 脚本:grep 'delete ' 于 OWL 模板 |
| 视图必填联动 readonly | E1 | phase2-design 检查项 |
| 继承视图 evergreen 锚点 | E1 | memory 保留(判断类) |
| stored compute 跨模块 depends | E1 | phase2-design 检查项 |
| 唯一性校验 create/write 重写 | E1 | phase2-design 检查项 |
| 接口日志 is_success 派生 | E2 | 脚本:grep is_success.*True 硬编码 |
| jenkins 空选择参数传空格 | E3 | jenkins MCP 内建(已有) |
| 服务器 python3.12 + --no-http | E1 | phase5-release 指令 |
| odoo-bin 必须带 conf | E1 | phase4-verify 指令 |
| BOM 导入清空工序拆分 | E1 | memory 保留(业务知识) |
| Edit 追加必读真实结尾 | E0 | 工具使用习惯(文档) |
| 并发会话共用仓库 | E3(结构) | worktree-per-proposal(L3 试点) |

## 三、状态机兼容
- state.json schema 已对齐(modules/phase/milestones/budget),直接可用
- backlog.md 保留现有格式,session-start hook 的 sed 提取兼容 `## In Progress` / `## Blocked`
- stack-profile 建议值:lint_cmd=`python -m pyflakes {changed_files}`,ci.type=jenkins,ci.trigger_ref=`mcp:jenkins`,branch_model=`feature→test`

## 四、迁移顺序(立项后)
1. L0:根目录放 stack-profile.yaml(不动任何现有文件)
2. 装插件启用 hooks(观察 1 周,收集误报)
3. 决策树章节逐章替换为技能引用,99-decision-tree.md 退役为历史文档
4. 20 条记忆按上表晋升 E2/E3
5. L3 试点:选低风险需求走 worktree-per-proposal
```

- [ ] **Step 4: 追加文档检查到 validate_plugin.sh**

```bash
# 8. 文档存在且非空
for d in architecture.md adoption-guide.md mes-migration-guide.md; do
  [ -s "$ROOT/docs/$d" ] || err "缺文档: docs/$d"
done
```

- [ ] **Step 5: 运行验证**

Run: `bash tests/run_all.sh` → Expected: VALIDATE PASS,FAIL=0

---

### Task 14: E2E 自测(scratch 项目端到端)

**Files:**
- Create: `tests/e2e.sh`
- Create: `tests/e2e-manual-checklist.md`

**Interfaces:**
- Consumes: 全部前序产物;Produces: E2E PASS/FAIL + 手工验证清单(即 adoption-guide 中的 LLM 行为项)

- [ ] **Step 1: 创建 tests/e2e.sh**

```bash
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
```

- [ ] **Step 2: 创建 tests/e2e-manual-checklist.md**

```markdown
# E2E 手工验证清单(LLM 行为项)

> 自动脚本(tests/e2e.sh)只覆盖 hook/脚本行为;以下项需在装好插件的真实会话中人工验证。

- [ ] 新会话启动 → 看到 backlog/state 摘要注入(≤40 行)
- [ ] 说"初始化项目" → ai-init 触发,交互式收齐 stack-profile 字段
- [ ] 说"我有个想法" → phase0-proposal 触发,产物落 .claude/proposals/
- [ ] Phase 1 产物缺失时说"推进" → gate-check 拒绝并列出缺失项
- [ ] 犯错被纠正后 → mistake-retro 提议记忆 + rules-registry 登记
- [ ] 改代码后结束回合 → Stop hook 警告 backlog/state 未同步
- [ ] lint 失败时 git push → 被阻断并显示原因
```

- [ ] **Step 3: 运行 E2E**

Run: `bash tests/e2e.sh`
Expected: `E2E PASS(scratch: /d/workspace/tmp/ai-factory-e2e)`

- [ ] **Step 4: 全量回归**

Run: `bash tests/run_all.sh && bash tests/e2e.sh`
Expected: 全部 PASS,FAIL=0

---

## Self-Review 记录

- **Spec 覆盖**:spec §五 全部产物 → Task 1-13;§六 profile → Task 2/7;§七 hooks → Task 3-6;§八 skills → Task 9-11;§九 闭环 → Task 11;§十 agents → Task 12;§十一 采用/回灌 → Task 13;§十二 自测 → Task 14。spec §六 漏定义 `security.protected_paths` → Task 1 Step 1 已修订
- **无 git 约束**:全部 Task 无 commit 步骤,完成标志=测试通过
- **类型一致**:`profile_get`/`profile_array` 签名(Task 2)与 Task 3/6/9 调用一致;模板占位符集合(Task 7)与 init render(Task 9)一致;清单文件名(Task 8)与 Task 10/11 引用一致;agent 名称(Task 12)与 Task 11 引用一致

## 执行偏差记录(2026-07-25 执行时修正,以代码为准)

1. **profile.sh 引号剥离**:`.strip("\"')` 会连剥内层引号(值以异种引号结尾时)→ 改为只剥外层成对引号
2. **Windows python 输出污染**:Git Bash 管道中 python 默认 cp936 编码 + `\r\n` 行尾,中文变乱码、行间残留 `\r` 破坏 bash 逐行处理 → 所有脚本内 python 统一 `sys.stdout.reconfigure(encoding="utf-8", newline="\n")`;validate_plugin.sh 额外 `tr -d '\r'` 兜底
3. **测试夹具自匹配**:假 lint 的标记字符串(FAILMARKER)会命中 stack-profile.yaml 自身 → mkrepo 改为自写 profile 并提交,保证变更集只含测试文件;用例2 增加 stderr 断言(阻断原因必须是 "lint 未通过",排除 eval 解析失败假象)
4. **e2e.sh 同理**:git init 后先提交骨架再跑场景 A
5. **validate_plugin.sh 路径风格**:内嵌 python 代码必须用 `pwd -W`(d:/...)而非 `pwd`(/d/...),Windows 原生 python 不认 MSYS 路径

## 执行结果(2026-07-25)

- 14/14 Task 完成;单元 4/4 套件 PASS(validate / profile / hooks×9 用例 / init)+ E2E PASS
- ai-factory 目录无 git,finishing-a-development-branch 技能不适用(用户显式指令优先)
- 手工验证清单:tests/e2e-manual-checklist.md(LLM 行为项,需装插件后在真实会话验证)
