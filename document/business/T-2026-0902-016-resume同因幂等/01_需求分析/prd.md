# PRD:resume 同因幂等提示(防确定性 bug 连撞)

- 工单:`pool/tickets/T-2026-0902-016.yaml`
- 阶段:P1 需求分析
- 关联规则:R12(`.claude/rules-registry.md`)
- 溯源事故:T-2026-0902-011(deploy 路径闸确定性误报被反复 resume 三连挂,
  incident T-2026-0902-014 复用三次)

## Why

工单挂起后,`resume`(CLI `orc resume` + dashboard `/resume` POST)只负责把状态
拨回 `resume_state` 重跑,**不校验"本次与上次挂起是否同一根因"**。确定性平台 bug
(不随重试消失)因此被反复 resume 连撞:

- 实证(T-2026-0902-011):deploy 依赖闸读错路径(`releases/current` 服务器不存在),
  是确定性误报——重试多少次结果都一样。但它被 resume 重跑三次,三次撞同一闸、
  三次挂起,连锁触发 incident 复用三次。
- 后果:resume 的"无脑重跑"放大了单点平台 bug 的破坏面,既烧 token 又制造
  重复 incident 噪声,把"一个待修的 bug"搅成"一串看似多发的故障"。

不修的代价:任何确定性挂起因都会被人工/循环反复 resume 连撞,根因被淹没在重试里。

## What

resume 入口增加**同因幂等提示**:若工单本次 resume 的 `reason_code` 与该单
**上一次挂起的 reason_code 相同**,默认给出警告并要求显式确认才执行;根因已变
(reason_code 不同)或无历史挂起,则正常放行。

功能要点:

1. **同因检测**:从工单事件流取最近一次 `suspended` 事件的 `reason_code`,
   与当前待恢复工单的挂起 `reason_code` 比对。
2. **警告+显式确认**:同因 → 提示"上次同因挂起,根因未变,直接 resume 大概率
   再撞同一闸,请先修根因";CLI 需 `--force`、dashboard 需勾选确认才执行。
3. **正常放行**:reason_code 不同(根因已修)或首次 resume(无历史挂起)→
   无警告直接恢复。
4. **留痕**:同因警告/强制恢复行为写事件流,可审计。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| AC1 | 同一 reason_code 连续 resume(第二次起) | 给警告,未带 `--force`/未确认时**不执行** resume |
| AC2 | 同因但带 `--force`(或 dashboard 确认) | 正常 resume,事件流留"同因强制恢复"记录 |
| AC3 | reason_code 与上次不同(根因已修) | 无警告直接放行 |
| AC4 | 工单无历史挂起事件(首次 resume) | 正常放行,无警告 |
| AC5 | CLI 与 dashboard 两入口 | 同因检测与确认语义一致 |
| AC6 | 现有 resume 正常路径 | 零回归,`pytest tests/` 全绿 |
