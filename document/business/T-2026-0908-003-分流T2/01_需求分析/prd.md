# PRD — T-2026-0908-003 分流 T2

## Why

T1 网关已通三渠道,但调用方递不出模型名,k2.6 路由组接不到流量;deepseek 文本层仍是付费兜底(本周 149M);W1 金丝雀无度量。本单接通"level→驾驶员"全链,并把 deepseek 文本层切到免费渠道。

## What

| # | 需求 | 验收标准(可判定) |
|---|---|---|
| R1 | runner 两处 packet 注入点按 ticket.level 解析驾驶员:L2/L3→'k2.6',L1→_model_for 现值(零变化) | 单测:L3 工单 packet.model=='k2.6';L1 工单==现值;无 level 存量单==现值 |
| R2 | claude_code 适配器 --model 白名单传递:packet.model ∈ {k2.6, gpt-6-astra} → cmd 含 --model;其余值/None → 不传(现行为) | 单测:白名单值出现在 cmd;deepseek-v4-flash/None 不出现 |
| R3 | zy-ds 移入缺省链(glm-flash 之后、ds-flash 之前);zy-k2/zy-gpt 保持 routeOnly | node 测试:缺省链=[kimi1-4, glm-flash, zy-ds, ds-flash, zen-k3];k2.6 路由组不变;全量 30+ 绿 |
| R4 | scripts/canary-report.py:周度聚合工单×级别×驾驶员×任务数×一次通过率×返工×consult + relay /__stats 渠道用量段 + 控制台读数手填位;markdown 输出 | 脚本对当前 pool 跑出表;含 006/T1 两张真实工单行 |
| R5 | docs/orchestrator-guide.md 增"分流与 W1 金丝雀"段:自动路由口径/交互式 --model k2.6 或 ANTHROPIC_MODEL 姿势/台账节奏/回退姿势 | 文档段落存在且命令可执行 |

## 验收标准(整单)

- pytest tests/ 全量零红;node --test 全量零红
- relay 重启后:缺省链八层含 zy-ds;kimi 冷却后 deepseek 层落 zy-ds(伪造冷却验证)
- 端到端:L3 工单 runner 派发 → claude -p --model k2.6 → relay 落 zy-k2(隔离池+伪造 adapter 验证,不烧真钱)

## 风险与边界

- --model 白名单只认两个路由组键,dsh 语义模型(deepseek-v4-flash)不会被误传给 claude CLI
- zy-ds 入缺省链不改变模型族(v4-flash→v4-flash),无降级;渠道收回→冷却滑 ds-flash(现行为)
- 台账脚本只读 pool/relay,不写任何状态
