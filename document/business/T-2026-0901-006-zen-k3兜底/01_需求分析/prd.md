# PRD:relay 翻译层 zen-k3 兜底(incident)

## Why

- 2026-09-01 晚:k3 双 key 周额度耗尽双双冷却,claude 链路 502 断流——这正是当初要解的痛点,T-2026-0901-001 方案 B(OpenAI 路由组)没有覆盖它(boss 当面指出)
- Zen /messages 对本账号不可用(kimi-k3 500×3、claude 全 disabled,三次复测一致);/chat/completions 的 kimi-k3 稳定 200,余额 $30
- 唯一通路:relay 内置 Anthropic↔OpenAI 翻译,zen-k3 作 failover 组第三后端

## What

1. relay 新增翻译模块:Anthropic 请求(messages/system/tools/tool_result/max_tokens)→ OpenAI chat/completions;上游恒非流式;OpenAI 响应(content/tool_calls/usage/finish_reason)→ Anthropic message;客户端要流式则合成 Anthropic SSE 事件序列
2. failover 组追加 zen-k3(kimi1→kimi2→zen-k3),仅当前两者冷却时承接;reasoning/thinking 块丢弃(保底出字优先)
3. k3 水位隔离不变(zen 计量不计入);zen-k3 消耗走 rates.opencode 周对账

## 验收标准

- 翻译单测(node --test):纯文本/带 system/带 tools/tool_result 往返;SSE 合成事件序列完整(message_start→...→message_stop)
- 活集成(真实 key):钉选 zen-k3 后 /v1/messages 200 + Anthropic 形状;带 tools 请求返回 tool_use 块
- claude -p "只回复两个字:就绪" 钉选 zen-k3 真实出字;/__use/auto 恢复后 kimi 链路回归
- zen-k3 请求落 stats(zen 或 zen-k3 键,不进 k3 水位)
