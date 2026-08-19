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
