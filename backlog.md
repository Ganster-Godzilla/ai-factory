# ai-factory 需求池 / 进度看板

> 会话启动读取;任务完成时更新(/ai-factory:backlog-sync)。

## In Progress
(空)

## Blocked
| 日期 | 事项 | 阻塞原因 |
|---|---|---|
| 2026-08-29 | dsh usage trailer 降级后遗症(T-2026-0828-003 hotfix a7de5d1 遗留,仅存在于 integration 分支,未进 main) | 无 trailer 时台账记 0 → DS 日现金闸/单工单预算闸失效;3 个旧契约测试(test_dsh_adapter)红;USAGE_MISSING_MSG 文案与新行为矛盾。需立案决定:修测试对齐新契约 or 恢复硬契约 |

## Done
| 日期 | 事项 |
|---|---|
| 2026-08-29 | PROJ-20260829-001 Dashboard v2 **delivered**:工单中心/项目中心泳道图/总览可导航化;main 合入 ffe2e20;44/44 单测绿 + 真实 pool 冒烟通过;评审 12 条全处置 |

## 关键决策
| 日期 | 决策 | 理由 |
|---|---|---|
| 2026-08-29 | Dashboard v2 形态:工单中心(筛选/搜索/排序)+ 项目中心泳道图(行=项目×列=阶段)+ 总览最小改动 | 与提出人对齐;Ticket 自带 project 字段,纯展示层;甘特/首屏重做已否决 |

## 下一步
Dashboard v2 已交付(main ffe2e20),重启 dashboard 进程即生效。优先处理 Blocked 项:dsh trailer 降级后遗症立案(涉及 DS 现金闸失效,integration 分支合 main 前必须解决)。
