# ai-factory 需求池 / 进度看板

> 会话启动读取;任务完成时更新(/ai-factory:backlog-sync)。

## In Progress
(空)

## Blocked
(空)

## Done
| 日期 | 事项 |
|---|---|
| 2026-09-01 | **T-2026-0901-004 部署契约交付(发布 v1.0.0,进观察窗)**:release 契约补"部署"环节——发布=合并→tag→deploy 脚本→冒烟→记录五步,部署执行在脚本里不靠人记得;deploy.py 单模块 + orchestrator.yaml deploy 段(remote/local 双形态)、冒烟检查器(URL 重试全 200)、依赖/.env 差异前置(.env 只比 key 名)、失败自动建 incident+回滚方案可照抄、artifacts P5 扩三章+SKILL 五步契约+deploy-runbook 五坑;G7 本地演示+失败路径演示、G8 sk-video-studio 真机远程演示均留痕;P4 黑盒 8/8 全绿。发布员实跑全量 353 绿(5 失败为沙箱环境性存量,bash CreateFileMapping 被拒,基线同款已核);check-pool-load 0 bad;deploy local 流水线 exit 0 冒烟 200;tag v1.0.0(本仓首个),合 main 940d097 |
| 2026-09-01 | **T-2026-0901-019 k3-c 第三账号入共享池交付,进观察窗**:failover 组 kimi1/2/3→zen-k3;node 14 绿;钉选 kimi3 实测 200(k3-c 真实可用);水位 kimi* 前缀自动覆盖;relay f18f43f/factory 8c2ea24。注:check-pool-load 现红于 T-2026-0901-007(并行会话 p5_releasing tasks 空,Owner 须按 R10 灌任务,本会话未代补——在飞票据防竞态) |
| 2026-09-01 | **T-2026-0901-006 relay 翻译层 zen-k3 兜底(incident)交付,进观察窗**:k3 双 key 周额度耗尽双双冷却 502 断流,boss 当面指出方案 B 未覆盖核心诉求;relay 内置 Anthropic↔OpenAI 翻译(relay-translate.js 纯函数)+ zen-k3 第三后端,双 kimi 冷却自动切 kimi-k3;修 /v1/v1 404 与 gzip 爆解析两个集成 bug;node 14 绿(活集成 JSON/SSE/真实工具调用)+pytest 358 绿;claude -p 全程 zen 出字;relay c8d627a/factory 0f5cf00。成本警示:兜底单会话 ~¥10 输入价,救命通道非日常 |
| 2026-09-01 | **T-2026-0901-001 模型网关接入 OpenCode Zen(方案 B)交付,进观察窗**:原 Anthropic 兜底方案实测证伪(/messages 全模型 500/disabled),boss 决策改 **zen 独立 OpenAI 路由组**(relay /zen/<path> 透传,独立计量不进 k3 水位,rates.opencode ¥21.6/108 周对账);修两个真 bug(/__use 连字符截断、gzip 绕过 token 统计);node 7 绿(活集成 kimi-k3 200)+pytest 11 绿+生产实测 200;relay e43aefc / factory 25f9b19。**R10 同日晋升 E2**(两起执行脱钩触发红线);事故:钉选未验证后端全停 8 分钟(入 ops-lessons#17)。遗留另立:F6 dsh provider 接线、F7 claude 兜底翻译层、F5 Zen 硬现金闸 |
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
