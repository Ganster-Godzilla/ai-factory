# PRD:runner 推进读 QA verdict(不只认退出码)

- 工单:`pool/tickets/T-2026-0902-015.yaml`
- 阶段:P1 需求分析
- 关联规则:R11(`.claude/rules-registry.md`)
- 溯源事故:T-2026-0902-010(QA 写"不通过/D1 P0"仍被推进 p5)

## Why

编排器状态机推进 `p4_verifying → p5_ready` 的唯一依据是 agent 进程退出码
(`orchestrator/daemon/runner.py:405` 判 `role_run.status == "done"`),**完全不读
QA 验收报告的结论**。这导致质量闸失效:

- 实证(T-2026-0902-010):QA 报告结论写"**不通过**,D1 为本单引入 P0",但 agent
  干净退出,runner 照样推进 p5_ready,带病工单递到 release 合并前全量测试才炸。
- 后果:质量闸回答的是"程序跑完没",不是"事做对没"——审核角色的结论被架空,
  任何"报告写不通过但程序正常退出"的场景都会放行,破坏面覆盖所有经 p4 的工单。

不修的代价:每次 QA 判负都要靠人工在 release 阶段兜底,p4 闸形同虚设,"老出事故"。

## What

在 `p4_verifying → p5_ready` 推进前增加 **verdict 闸**:从 QA 验收报告中解析显式
判定,仅"通过"放行;"不通过/缺结论/无法解析"一律按不通过处理(挂起退回,fail-closed)。

功能要点:

1. **verdict 解析**:读 QA 验收报告(`04_测试/验收报告.md`)的"结论"章节,
   识别通过/不通过判定;锚定该页独有标题,防导航栏/通用词误判(R6)。
2. **闸接入**:runner 在 p4→p5 `transition` 前先过 verdict 闸,落在
   `orchestrator/daemon/gates.py`(与现有产物门禁同层,统一 GateFailed 语义)。
3. **fail-closed**:报告缺"结论"章节、解析不到明确判定 → 视为不通过,挂起,
   不静默放行。
4. **留痕**:verdict 判定结果写事件流(`verdict=pass/fail` + 来源),可审计。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| AC1 | QA 报告结论写"不通过" | runner **不推进** p4→p5,工单挂起,事件流留 `verdict=fail` |
| AC2 | 报告结论写"通过"且产物门禁过 | 正常推进 p5_ready,事件流留 `verdict=pass` |
| AC3 | 报告缺"结论"章节 | 按不通过处理(挂起),不静默放行 |
| AC4 | 结论章节无法解析出明确判定 | 按不通过处理(挂起),不静默放行 |
| AC5 | 现有 p4→p5 正常路径(报告写通过) | 零回归,`pytest tests/` 全绿 |
| AC6 | verdict 判定来源(报告路径+结论原文) | 写入事件流,可回溯 |
