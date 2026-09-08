# PRD — T-2026-0908-001 zheyuan 渠道三通道入网关

## Why

分流减员计划(k3 4 账号 ¥2796/月 → 目标减半以上)的硬前置:渠道三 key 已入册且探活全通,但网关不认识它们,全部流量仍走 kimi 付费池。本单让 relay 能把 L3/L2 流量引去 k2.6(免费),同时官方 key 全留链尾当熔断备份。

## What

| # | 需求 | 验收标准(可判定) |
|---|---|---|
| R1 | BACKENDS 增 zy-k2(Anthropic 原生,model 重写 kimi-k2.6)、zy-gpt(translate,gpt-6-astra)、zy-ds(translate,deepseek-v4-flash);三 key 从 zheyuan-k2/gpt/ds.env 加载,缺失即启动失败列出 | 单测:relay 启动 /__status backends=10;三新后端 key 加载成功 |
| R2 | 按模型路由组:model='k2.6' → [zy-k2, zy-ds, glm-flash, ds-flash, kimi1-4, zen-k3];model='gpt-6-astra' → [zy-gpt, kimi1-4, zen-k3];其余 model → 现顺位(零变化);pinned 优先级不变 | 单测:三模型各取链断言;伪造冷却后断言顺位跳过;缺省链与现 BACKENDS 顺序一致(回归) |
| R3 | 熔断/翻译语义沿用:FAILOVER_CODES/冷却分级/settled 守卫/translate 路径对新后端一致生效 | 单测:既有 node 测试全套全绿(回归);新后端走 translate 路径的断言 |
| R4 | 活冒烟:三新后端各 1 次真实调用通;k2.6 模型请求落点在 zy-k2;/__stats 三新后端计量非零 | 冒烟脚本输出 + /__stats 读数 |

## 验收标准(整单)

- R1-R4 全绿;`node --test test/` 全量零红
- relay 重启后 /__status 十后端在线;kimi 池水位路径(编排器 gateway.py /__stats 合计 kimi*)不受影响
- 回滚=revert + 重启 relay, kimi 池行为不变

## 风险与边界

- relay 是 k3 池咽喉:改动纯增量(新后端追加在链尾/新路由组),缺省链零变化;重启窗口秒级
- zy-k2 走透传+model 重写(既有 L254 路径),不引入新代码路径;zy-gpt/zy-ds 走 translate(0903-011 已修复件)
- 渠道免费账号被收回/限速 → 冷却自动滑向下一层,业务无感(设计内)
