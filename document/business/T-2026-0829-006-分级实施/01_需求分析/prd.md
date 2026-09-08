# PRD — T-2026-0829-006 任务分级快速通道实施单(L1 现状 + L3 快速通道落地)

> 依据：策略权威文档 `document/business/T-2026-0828-004-任务分级/02_设计文档/strategy.md`(已评审)。
> 提案:`../00_提案/提案.md`(boss 已批准入 P1)。本 PRD 不复制策略全文,只落需求口径与验收标准。

## Why

策略文档(T-2026-0828-004)已评审落地,但**系统行为零变化**:工单没有 level 字段、状态机没有 L3 短路边、建单没有 --level 参数、门禁不分级、Dashboard 不可见。策略是纸面规则,简单任务仍被迫走完整 P0-P5,流程成本倒挂(策略实证:T-001 冒烟单跑半天)。

同时,分流驾驶(模型按工单级别路由)等下游能力需要 level 作为判据——本单是硬前置。

## What

按提案范围做**最小可用落地**:只落 L1(现状语义)+ L3(快速通道)两档行为;L2 裁剪、frequency_alert 频度告警、L3-manual 报备流、观察窗 window_hours 接线**全部不做**(留后续单,见策略"不做"条款)。

| # | 需求 | 验收标准(可判定) |
|---|---|---|
| R1 | Ticket 新增 `level` 字段(L1\|L2\|L3);存量 yaml 无字段 load 兜底 L1;`validate()` 拒绝取值域外值;`orc new --level`(缺省 L1 保守) | 单测:缺字段工单 load 后 level==L1;level="L4" save_ticket 拒入;`orc new --level L3` 建单后 yaml 含 `level: L3`;缺省建单 level==L1 |
| R2 | 状态机 L3 条件边:`p0_proposed→p3_queued`(actor=boss,仅 level==L3 放行);`p5_releasing→done`(actor=release,仅 level==L3,事件记 `monitoring_skipped=true`) | 单测:L3 单两条边可走;L1 单走同边抛 IllegalTransition;L3 走 p5_releasing→done 后事件含 monitoring_skipped |
| R3 | 审批目标按级别解析:`approval_target(ticket)`:p0_proposed 态 L3→p3_queued、L1/L2→p1_drafting;CLI approve 与 Dashboard 审批中心**共用**该解析(双入口同口径) | 单测:L3 单 approve 后落 p3_queued;L1 单落 p1_drafting 不变(回归) |
| R4 | runner 熔断参数按级别:L3 重试上限收紧 ≤2、免会诊,达上限 `suspend(reason_code=circuit_exhausted)`;L1/L2 行为零变化 | 单测:`next_action(task, "L3")`:attempts<2→retry,=2→suspend(无 consult 分支);L1 现行阶梯回归全绿 |
| R5 | 门禁按级别裁剪:L3 单只守**不可省四项**(发布批准/验收命令执行/台账入账/状态机迁移,策略封闭清单),豁免 P0/P1/P2/P4/P5 全部产物文件校验;P3 边 task_verify_required 保留(验收命令执行不可省) | 单测:L3 单无任何产物文件过 P0/P1/P4 门禁边 check_gate 返回空;P3 边任务 verify 非 passed 仍拦;L1 单产物缺失照拦(回归) |
| R6 | Dashboard 最小展示:工单中心列表加"级别"列(L1/L2/L3 分色徽章,L3 即快速通道标记);详情页显示当前级别卡片 | 单测:列表渲染含 level 徽章;详情页渲染含级别卡;存量单(无 level 字段)渲染不炸(兜底 L1) |

## 验收标准(整单)

- R1-R6 逐项对应单测全绿;`pytest tests/` 全量回归零红
- `python -m pyflakes` 改动文件零告警
- 合 main 前 `check-pool-load.py` / `check-complexity.py` 过闸
- 演示路径:`orc new --level L3` 建单 → approve 直落 p3_queued → … → p5_releasing→done(monitoring_skipped),Dashboard 全程可见

## 风险与边界

- 存量 76 单无 level 字段:load 兜底 L1 = 行为不变(纯增量,revert 即回滚)
- incident 快速通道(既有豁免)与 L3 快速通道语义正交,不合并
- L2 档本单仅允许作为字段值存在(行为同 L1),不做任何流程裁剪
