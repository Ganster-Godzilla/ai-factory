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
