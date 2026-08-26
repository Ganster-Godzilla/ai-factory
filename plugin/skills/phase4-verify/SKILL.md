---
name: phase4-verify
description: Phase 4 测试验证。实现完成进入系统测试/黑盒验证时使用。
---

# Phase 4 — 测试验证

## 产物
- 测试报告:环境 / 范围 / 用例结果 / 缺陷清单 / 结论
- 黑盒验证记录:验证人 + 日期 + 结论

## 规则
- 测试环境尽量贴近生产;记录环境差异
- **全绿 ≠ 实跑**:必须核对用例执行数,0 执行按失败处理
- 遗留缺陷逐条登记 backlog,禁止口头遗留
- 发现新问题且需改代码 → 回到 phase3-implement(小修)或 phase2-design(动边界)

## 门禁
gate-check(phase4)
