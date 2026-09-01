# ai-factory 需求池 / 进度看板

> 会话启动读取;任务完成时更新(/ai-factory:backlog-sync)。

## In Progress
(空)

## Blocked
| 日期 | 事项 |
|---|---|
| 2026-09-01 | **T-2026-0901-001 模型网关接入 Zen 兜底(suspended,等 Zen 充值)**:代码全部完成并合 main——relay zen-kimi 第三后端(K1/K2 冷却自动溢出 kimi-k3)+ /__use 连字符修复;k3 水位只计 kimi*;rates.opencode ¥21.6/108;zen-usage-ledger.py 周对账;guide 一节。**Z5 未做**:Zen 0 余额(付费模型 401/免费模型 disabled),充值后 resume:relay 无需重启,跑直连 200/钉选/水位/台账 dry-run/claude 链路+04/05 文档 |

## Done
| 日期 | 事项 |
|---|---|
| 2026-08-30 | **T-2026-0830-001 产物布局统一交付**:全阶段产物工单文件夹化(00_提案/01_需求分析/02_设计文档/04_测试/05_部署交付),manifest 9 路径+resolve_artifact_path 统一解析器;两仓迁移(ai-factory 9 夹+sk 4 夹);本单全程新门禁 dogfood 通过,合 main,工单 done |
| 2026-08-29 | **T-2026-0828-004 任务分级与快速通道策略交付(纯文档单)**:strategy.md 落盘——L1/L2/L3 就高判定、L3 最短路+人工报备、不可省门禁四项封闭清单、L3 熔断收紧、level 字段与 Dashboard 口径;六段 doccheck 验收一次过,合 main 6e5527b,工单 done。**ai-factory 工单池清零收官** |
| 2026-08-29 | **T-2026-0829-001 阶段产物与门禁口径统一交付**:ARTIFACT_MANIFEST 单一事实源+迁移级闸门;评审两轮 23 项全处置;合 main e46484f,工单 done |
| 2026-08-29 | **T-2026-0829-002 dsh 会话文件真实计量交付**:台账估算→真账;评审两轮 27 项全处置;223 绿,合 main b145a26,工单 done |
| 2026-08-29 | **T-2026-0829-004 dsh 现金闸"明放"交付**:估算入账+双闸 warn-only+复审提醒;integration 合 main;合 main 6740b53,工单 done |
| 2026-08-29 | T-2026-0828-005 事故单关闭:github 抖动致 push 失败,网络恢复后补推 sk 仓 main+v0.1.0/v0.1.1 双 tag 远端核验 |
| 2026-08-29 | PROJ-20260829-001 Dashboard v2 **delivered**:工单中心/项目中心泳道图/总览可导航化;main ffe2e20(补登单 T-2026-0829-003) |

## 关键决策
| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-09-01 | **R10 晋升 E2**:check-pool-load.py 增"p3+ 状态 tasks 非空 / p2_approved 挂 *_commit 即 FAIL",历史单豁免 | 同日两起"建单后脱钩执行"(001 过门禁后 tasks 空跑完开发;002 hotfix done tasks 空),触发"同 E1 违反 2 次必晋升" |
| 2026-09-01 | Zen 兜底语义:第三后端自动溢出(kimi-k3);Zen 消耗不占 k3 周水位,按费率周对账入台账(estimated) | 付费池与共享池性质不同;防 T-001 类闸污染;R9 账不可瞎 |
| 2026-08-29 | Dashboard v2 形态:工单中心(筛选/搜索/排序)+ 项目中心泳道图(行=项目×列=阶段)+ 总览最小改动 | 与提出人对齐;Ticket 自带 project 字段,纯展示层;甘特/首屏重做已否决 |
| 2026-08-29 | dsh 现金闸:磨合期允许临时放开,但必须"明放"(闸 warn-only + 估算入账,不记 0) | 失败重试多,硬闸卡死 pipeline;但无账则无数据评估放开是否合理、无法定阈值 |
| 2026-08-29 | 双轨融合规则:编排工单=系统账本,技能包=过程闸,执行可 runner 可交互;凡产生代码/文档变更的任务必建编排工单 | 纯技能包流实证代价:Dashboard v2 无台账痕迹+p1_round 事故绕开了发布验收闸 |
| 2026-08-29 | 明放四参数:复审双触发(2026-09-12 或 T-2026-0829-002 交付)/ 估算 ¥0.05/次 / 双闸均 warn-only / integration 先合 main | boss AskUserQuestion 逐项决策 |
| 2026-08-29 | integration 分支回卷丢弃 a7de5d1 后,从硬契约基线自行实现明放 | 降级代码已不存在,重实现反而干净;旧 3 红测试同机会改造 |
| 2026-08-29 | 明放复审(T-002 交付触发):mingfang 续期至 2026-09-12,不关闸 | boss 担心其他项目(SK 等)开发期失败重试被硬闸卡死;现有真实计量,超线全程可见 |

## 下一步
- **T-2026-0829-006(任务分级实施单)**:提案已备,p0_proposed 待 boss 批准(P0 门禁校验 00_提案/提案.md)。
- sk T-2026-0829-005 闭环后:补迁其工作件进工单文件夹;ai-factory docs/specs 下 005 残留件(baseline.json/dump_surface.py 与 sk 仓不一致)待 boss 处置。
- 明放续期至 2026-09-12(已复审,见关键决策):届时按真账再评;mingfang 复审横幅保留。
- 遗留边界(未来立案,已录 artifact-standard.md/backlog):并发 run 会话归属、GLM 会话格式未实证、门禁读当前分支、tasks TOCTOU、artifact_missing 挂起 resume 重跑角色。
