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
