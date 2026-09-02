# 设计:P3 执行层切 k3 订阅池

## Architecture

```
runner dev/qa/release/sre ──► k3 适配器(claude -p,Anthropic)──► relay :8787
  failover 组(逐层冷却滑动,全部复用既有熔断/翻译):
    kimi1(k3-a) → kimi2(k3-b) → kimi3(k3-c) → kimi4(k3-d)   [订阅,边际 0]
    → glm-flash(open.bigmodel.cn, glm-5.3-flash, translate)  [免费层]
    → ds-flash(api.deepseek.com, deepseek-v4-flash, translate)[¥1.5-9/1M]
    → zen-k3(opencode.ai/zen, kimi-k3, translate)              [¥21.6/108,$ 余额硬帽]
水位:kimi* 前缀合计(4 账号);glm/ds/zen 翻译后端各自独立计量,不进 k3 闸。
现金:ds-flash 消耗仍记 deepseek 台账(既有 dsh 计量管道不变?——见 How §4 口径)。
```

## How

1. **relay(B1-B3)**:`kimi-relay.js` BACKENDS 追加三项(kimi4 在 zen-k3 前;glm-flash/ds-flash 带 `translate:true` 与 keyFile glm/deepseek,base 各官方端点,model 固定);translate 路径已存在(006),新增后端零新逻辑;测试:后端名单断言 7 个 + 顺位(伪造冷却)/活集成(有 key 的层)
2. **runner(B4)**:`orchestrator/daemon/runner.py` ROLE_ROUTING dev/qa/release/sre 值 dsh→k3;`models:` 段 dev/qa 模型字段对 k3 适配器无意义(claude 自选),保留注释;dsh 适配器保留。**首验**:挑一张小额工单切片用 k3 适配器真跑 dev,产物真实可验;失败即回退 ROUTING
3. **水位闸(B5a)**:`orchestrator.yaml` k3_week_token_budget 150M→600M + 注释(2026-09-09 复审,按真实曲线定终值);gateway.py 水位口径不变(kimi* 前缀自动含 kimi4)
4. **台账口径(B5b)**:ds-flash 经 relay 的消耗目前只进 relay stats(池级),不进 per-ticket DS 现金——与 k3 同口径(池级);Dashboard 字段标注"仅 DeepSeek 通道(dsh 直调)";zen/glm/ds 各翻译后端的周量经 zen-usage-ledger 扩展(键 zen+zen-k3 既有;ds/glm 层本单只标口径,入脚本留后续)
5. **顺位演练(B6)**:测试环境 PORT 隔离,钉选/伪造冷却逐层断言候选顺序;生产 /__reset 后正常轮转

## Checkpoints

- node --test 全绿(7 后端 + 翻译活集成)
- 顺位演练:四层滑动行为符合设计(记录各层状态码)
- dev 小切片 k3 适配器首验通过(或回退并记录)
- pytest 全绿;check-pool-load 0 bad;Dashboard 标注可见

## Rollback

- relay:BACKENDS 摘三项 + 重启 → 回 4 后端
- runner:ROLE_ROUTING 回 dsh(一行)+ 重启;水位闸回 150M
- 台账/标注为增量,revert 即可
