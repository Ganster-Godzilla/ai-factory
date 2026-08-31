# PRD:模型网关接入 OpenCode Zen 兜底

## Why

- k3 双 key 周额度耗尽即断流,2026-08-27 单日 30 万 tokens,提额至 300 万/150M 仍紧张
- Zen 已开户且有余额,其 Anthropic 兼容端点(需 x-api-key,relay 恰好双头注入)可直接入 failover 组,零翻译成本
- 付费兜底必须计价:R9 纪律"闸可松账不可瞎",Zen 消耗按费率估算入台账,周对账

## What

1. relay 新增第三后端 zen-kimi(base=https://opencode.ai/zen,model 重写为 Zen 上 Kimi 模型 id),K1/K2 冷却时自动溢出;恢复靠现有 30min 冷却探测
2. k3 周水位闸只合计 kimi* 后端,zen-kimi 不污染 150M 预算(防 T-001 类闸误触)
3. orchestrator.yaml rates.opencode(¥4.3/¥21.6 per 1M tokens,汇率假设注释);scripts/zen-usage-ledger.py 读 /__stats 的 zen-kimi 周 tokens 折算 CNY 入 ledger(estimated=true)
4. guide 文档新增「Zen 兜底」一节:语义、钉选 /__use/zen-kimi、对账脚本用法

## 验收标准

- `cd /d/Tool && node --test test/` 全绿(含新增 zen 用例:3 后端、钉选、model 重写)
- `pytest tests/orchestrator/test_gateway.py` 等全绿:stats 含 zen-kimi 时水位不含其 tokens
- 重启 relay 后 /__status 显示 3 后端;钉选 zen-kimi 发 claude 格式 /v1/messages 得 200
- /__stats 中 zen-kimi 周 tokens 增长且 k3_effective_week_tokens 不含 zen 部分
- zen-usage-ledger.py dry-run 产出 estimated=true 台账条目
- claude -p 经 relay 真实调用成功(主走 kimi,zen 仅冷却时承接)
