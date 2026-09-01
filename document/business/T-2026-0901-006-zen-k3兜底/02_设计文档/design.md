# 设计:relay 翻译层 zen-k3 兜底

## Architecture

```
claude(Anthropic)──► relay failover 组:kimi1 → kimi2 → zen-k3(仅前两者冷却时)
                                                    │ translate
                                                    ▼
                                     opencode.ai/zen/v1/chat/completions(kimi-k3,恒非流式)
                                                    │
              ┌── client stream=false: Anthropic message JSON
              └── client stream=true : 合成 SSE(message_start→block(s)→message_delta→message_stop)
```

翻译模块 `D:\Tool\relay-translate.js`(纯函数,node --test 可单测):
- `toOpenAI(reqBody, model)` → {model, messages, max_tokens, tools?, tool_choice?}
  - system(字符串或块数组)→ 首条 system 消息;text 块拼接;assistant 的 tool_use → tool_calls;user 的 tool_result → role:tool 消息;image/其他块 → 文本占位丢弃
- `toAnthropic(oaiResp)` → Anthropic message JSON(id/type/role/content/stop_reason/usage);tool_calls → tool_use 块;finish_reason 映射(stop→end_turn, tool_calls→tool_use, length→max_tokens)
- `toAnthropicSSE(anthropicMsg)` → SSE 字符串序列

## How

1. `relay-translate.js` + `test/relay-translate.test.js`:四组往返用例 + SSE 序列断言(含 tool_use)
2. `kimi-relay.js`:BACKENDS 追加 `{ name:'zen-k3', base:'https://opencode.ai/zen/v1', keyFile:'opencode', model:'kimi-k3', translate:true }`;tryBackend 内 translate 分支:body 翻译后上行;响应缓冲全量(不 pipe 流)→ toAnthropic → 按 parsed.stream 回 JSON 或 SSE;usage 从 OpenAI usage 记账
3. 活集成(test/relay-zen.test.js 追加):钉选 zen-k3 → /v1/messages 200 Anthropic 形状;带 tools 请求得 tool_use
4. 生产:重启 relay → /__reset → 钉选实测 curl + claude -p → /__use/auto → 主链路回归

## Checkpoints

- `node --test test/` 全绿(翻译单测 + 活集成)
- 钉选 zen-k3:curl /v1/messages 200 Anthropic 形状;claude -p 真实出字
- /__stats zen-k3(或 zen)计量增长,kimi 水位不变
- auto 模式:双 kimi 冷却时 claude 请求经 zen-k3 出字(本工单验收时的真实场景)

## Rollback

- BACKENDS 摘 zen-k3 + 重启 relay → 回方案 B 现状(断流但无新风险);翻译模块纯新增,摘除无残留
- Zen 计费:兜底期间按 rates.opencode 入账;余额耗尽时 zen-k3 同样 401 冷却,行为=现状
