# PRD:模型网关接入 OpenCode Zen 兜底

## Why

- k3 双 key 周额度耗尽即断流,2026-08-27 单日 30 万 tokens,提额至 300 万/150M 仍紧张
- Zen 已开户且有余额,其 Anthropic 兼容端点(需 x-api-key,relay 恰好双头注入)可直接入 failover 组,零翻译成本
- 付费兜底必须计价:R9 纪律"闸可松账不可瞎",Zen 消耗按费率估算入台账,周对账

## What

1. relay 新增 **zen 独立 OpenAI 路由组**:`/zen/<path>` 透传 `opencode.ai/zen/v1/<path>`,key 注入,模型客户端自选,独立计量(2026-09-01 变更:原"Anthropic 兜底后端"方案被实测证伪,Zen /messages 对本账号全部 500/disabled)
2. k3 周水位闸只合计 kimi* 后端,zen 计量不污染 150M 预算(防 T-001 类闸误触)
3. orchestrator.yaml rates.opencode(kimi-k3 ¥21.6/¥108 per 1M tokens,汇率假设注释);scripts/zen-usage-ledger.py 读 /__stats 的 zen 周 tokens 折算 CNY 入 ledger(estimated=true)
4. guide 文档「Zen 路由组」一节:用法、计量、对账

## 验收标准

- `cd /d/Tool && node --test test/relay-*.test.js` 全绿(failover 组双 kimi 不动;活集成:真实 key 下 /zen/chat/completions kimi-k3 → 200 + OpenAI 形状 + stats 落账)
- `pytest tests/orchestrator/test_gateway.py tests/orchestrator/test_zen_ledger.py` 等全绿:stats 含非 kimi 键时水位不计
- 生产 relay 重启后 /__status 双 kimi + routes.zen;实测 /zen/chat/completions 200
- /__stats 中 zen 周 tokens 独立增长,kimi 水位不变
- zen-usage-ledger.py --dry-run 产出估算金额;正式入账 estimated=true
- kimi 主链路回归:claude -p 经 relay 成功(不受影响)
- **变更留痕**:Anthropic 方案证伪的实测数据与决策记入 design.md 变更记录与本单事件流
