---
name: gate-check
description: Phase 门禁检查(刚性)。当用户说"推进""进入下一阶段""门禁检查""gate check"时必用;产物不齐时有权且必须拒绝推进。不可跳过。
---

# Gate Check — 刚性门禁

## 规则(不可协商)
1. 读 state.json 确定当前模块与目标 Phase
2. 读对应清单 `${CLAUDE_PLUGIN_ROOT}/templates/gate-checklists/phase{N}-gate.md`
3. **派发 ai-factory:gate-checker 子代理**在干净上下文逐项核查(避免自己查自己)
4. 输出逐项 ✅/❌ + 缺失项的具体路径
5. 存在任一 ❌ → **明确拒绝推进**,给出补齐路径。禁止"先推进后补票"
6. 用户要求跳过 → 引用本规则并拒绝;这是刚性门禁

## 全过后
- 更新 state.json:`milestones.<phaseN>=completed`、`phase` 推进、`last_updated`
- 更新 backlog.md 状态
- 告知用户可进入的下一 Phase 及对应技能名
