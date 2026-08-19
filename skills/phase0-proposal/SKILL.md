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
