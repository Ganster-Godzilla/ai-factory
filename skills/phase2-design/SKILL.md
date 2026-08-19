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
