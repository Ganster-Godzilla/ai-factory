#!/usr/bin/env bash
cd "$(dirname "$0")/.."
source plugin/scripts/lib/profile.sh
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
