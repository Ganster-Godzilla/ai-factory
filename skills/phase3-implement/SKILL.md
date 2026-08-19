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
