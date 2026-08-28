# ai-factory 需求池 / 进度看板

> 会话启动读取;任务完成时更新(/ai-factory:backlog-sync)。

## In Progress
| 日期 | 事项 | 状态 |
|---|---|---|
| 2026-08-29 | PROJ-20260829-001 Dashboard v2(工单中心/项目中心泳道图/总览可导航化) | Phase 3 实现完成(orc/dashboard-v2,44/44 绿,评审修复已合),待 Phase 4 验证 |

## Blocked
| 日期 | 事项 | 阻塞原因 |
|---|---|---|
| 2026-08-29 | dsh usage trailer 降级后遗症(T-2026-0828-003 hotfix a7de5d1 遗留) | 无 trailer 时台账记 0 → DS 日现金闸/单工单预算闸失效;3 个旧契约测试(test_dsh_adapter)红;USAGE_MISSING_MSG 文案与新行为矛盾。需立案决定:修测试对齐新契约 or 恢复硬契约 |

## Done
(空——编排器 M1-M4 历史见 docs/superpowers/plans/)

## 关键决策
| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-29 | Dashboard v2 形态:工单中心(筛选/搜索/排序)+ 项目中心泳道图(行=项目×列=阶段)+ 总览最小改动 | 与提出人对齐;Ticket 自带 project 字段,纯展示层;甘特/首屏重做已否决 |

## 下一步
Dashboard v2 进入 Phase 4 测试验证(/ai-factory:phase4-verify),通过后 Phase 5 合 main。dsh trailer 降级遗留见 Blocked,建议优先立案(涉及现金闸失效)。
