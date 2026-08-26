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
