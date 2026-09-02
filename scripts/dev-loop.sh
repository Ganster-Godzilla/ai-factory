#!/bin/bash
# dev-loop.sh <TICKET_ID> [PROJECT_DIR] — 工单 dev 驱动循环(2026-09-01,规则#11 版)
# 每切片 done 即合 main:后续工位从含前序成果的 main 切出,否则集成切片必崩。
# 冲突/index.lock/瞬态错误分级处理;终态(idle/suspend/failed)即停。
set -u
TID="$1"
AF=D:/workspace/ai-factory
SK="${2:-D:/workspace/sk-video-studio}"
cd "$AF" || exit 1
strikes=0
for i in $(seq 1 120); do
  echo "[$i] $(date +%H:%M:%S) advance $TID..."
  out=$(python -m orchestrator.daemon.cli advance "$TID" "$SK" 2>&1)
  rc=$?
  line=$(echo "$out" | tail -1)
  echo "  -> $line"
  if [ $rc -ne 0 ] || echo "$line" | grep -qE "Traceback|RuntimeError"; then
    strikes=$((strikes+1))
    echo "  transient err strike $strikes/3"
    [ $strikes -ge 3 ] && { echo "STOP: 连续瞬态错误"; echo "$out" | tail -5; break; }
    sleep 45; continue
  fi
  strikes=0
  case "$line" in
    task:*:done)
      sid=$(echo "$line" | cut -d: -f2)
      wt="$SK/.orc-worktrees/$TID-$sid"
      # 空心合并第四形态防线:dev 验收过但不提交 → 分支空 → merge 假成功。
      # 合并前先查分支有无提交;零提交且工位脏则自动补入账。
      if [ -d "$wt" ]; then
        ahead=$(cd "$wt" && git log --oneline "main..HEAD" 2>/dev/null | wc -l)
        if [ "$ahead" -eq 0 ]; then
          dirty=$(cd "$wt" && git status --short | grep -v " M .orc-base" | wc -l)
          if [ "$dirty" -gt 0 ]; then
            echo "  检出空心:dev 未提交($dirty 文件),工位自动补入账"
            (cd "$wt" && git add -A && git commit -m "chore($sid): dev 未提交产物补入账(loop 自动,规则#11)" >/dev/null 2>&1)
          else
            echo "  STOP: $sid 分支零提交且工位干净——真空心,需人工诊断"; break
          fi
        fi
      fi
      cd "$SK"
      ok=0
      for try in 1 2 3; do
        mout=$(git merge --no-ff "orc/$TID-$sid" -m "merge($sid): 切片即合 main(loop 自动,规则#11)" 2>&1)
        if [ $? -eq 0 ]; then
          # 真合并校验:分支必须成为 main 祖先(Already-up-to-date 也算过,但前提是分支有货)
          if git merge-base --is-ancestor "orc/$TID-$sid" main; then
            echo "  merged $sid"; ok=1; break
          fi
          echo "  STOP: $sid 假合并(ancestor 校验失败)"; break
        fi
        if echo "$mout" | grep -q "index.lock"; then echo "  index.lock 竞争,等 20s 重试 $try"; sleep 20; continue; fi
        bad=$(git diff --name-only --diff-filter=U 2>/dev/null)
        if [ "$bad" = ".orc-base" ]; then
          git checkout --ours .orc-base && git add .orc-base && git commit --no-edit >/dev/null 2>&1
          echo "  merged $sid (.orc-base 取主仓)"; ok=1; break
        fi
        echo "  MERGE-CONFLICT $sid: ${bad:-未知} — 已 abort,loop stop"
        git merge --abort 2>/dev/null
        break
      done
      cd "$AF"
      [ $ok -eq 0 ] && break
      ;;
    task_failed:*|suspend:*|blocked:*|idle:*|error*)
      echo "STOP: $line"; break;;
  esac
  sleep 3
done
echo "=== $TID loop exited $(date +%F' '%T) ==="
python - <<PY
import yaml, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
d = yaml.safe_load(open('pool/tickets/$TID.yaml', encoding='utf-8'))
print('state:', d['state'])
for t in d.get('tasks', []):
    print(' ', t['id'], t['status'])
PY
