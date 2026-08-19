---
name: mistake-retro
description: 犯错后或定期复盘:根因入记忆、规则沿 E0→E3 阶梯机制化晋升、登记 rules-registry。当发现错误/返工/被用户纠正时使用。
---

# Mistake Retro — 成长闭环

## 五问流程
1. **根因是什么?** → 写入项目记忆(type: feedback,含 Why + How to apply)
2. **能否机制化?** → 能:产出 E2(检查脚本)或 E3(hook)草稿
3. **不能机制化的原因?** → 纯判断类规则,留 E1 并记录原因
4. **登记** `.claude/rules-registry.md`:规则 / 等级 / 载体 / 日期 / 晋升历史
5. **验证**:下次同类场景应零复发;跟踪并在再犯时升级处理

## 晋升触发(刚性)
同一条 E1 规则**被违反 2 次 → 必须晋升 E2/E3**,不允许继续靠自觉

## 可选
派发 ai-factory:mistake-auditor 子代理扫描近期变更,交叉验证是否还有未登记的返工模式
