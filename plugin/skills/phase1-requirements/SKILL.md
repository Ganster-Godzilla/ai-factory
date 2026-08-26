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
