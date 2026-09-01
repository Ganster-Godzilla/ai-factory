# 设计:模型网关接入 OpenCode Zen(方案 B,2026-09-01 变更)

> **变更记录**:原方案(Zen 作 Anthropic 第三兜底后端,claude 流量自动溢出)**被实测证伪**——Zen `/messages` 端点对本账号全部模型返回 500/disabled(kimi-k3/k2.7-code/k2.6 500,claude-haiku-4-5 disabled,免费模型 disabled);仅 `/chat/completions`(OpenAI)可用(kimi-k3 200,$30 余额已充)。经 boss 决策改方案 B:zen 不进 failover 组,改独立 OpenAI 路由组,服务 dsh/工具类 OpenAI 协议消费者;claude CLI 的 k3 池兜底不在本单范围(翻译层另单评估)。事故与教训:钉选未验证后端致全停 8 分钟(ops-lessons#16);token 统计被 gzip 绕过(剥 accept-encoding 修复)。

## Architecture

```
claude / Anthropic 客户端 ──► relay :8787 ──failover 组──► kimi1 (api.kimi.com/coding, k3-a)
                                │                          kimi2 (api.kimi.com/coding, k3-b)
OpenAI 客户端(dsh/curl/工具)──► relay /zen/<path> ──透传──► opencode.ai/zen/v1/<path>(key 注入)
                                └─/__stats:zen 独立计量 ──► zen-usage-ledger.py × rates.opencode ──► ledger(estimated=true)
gateway.py k3 水位:只合计 kimi*(zen 路由组不计入,防闸污染)
```

## How

**D:\Tool(relay 仓,main):**
1. `keys\opencode.env`:真实 key 已填(gitignored)
2. `kimi-relay.js`:failover 组恢复双 kimi;新增 `ZEN` 路由配置 + `proxyZen()`(/zen/ 前缀剥离、x-api-key+Bearer 双头注入、剥 accept-encoding、OpenAI usage 字段统计);`/__status` 增 routes.zen;stats 加 zen 键独立计量
3. `test\relay-zen.test.js`:failover 组双 kimi + routes.zen 存在;活集成(需真实 key+余额):/zen/chat/completions kimi-k3 → 200 + OpenAI 形状 + stats 落账

**ai-factory(main):**
4. `orchestrator/daemon/gateway.py`:只合计 kimi* 后端(zen 自然排除;测试含非 kimi 键用例)
5. `orchestrator.yaml`:rates.opencode(kimi-k3 $3/$15 → ¥21.6/108 per 1M,cache ¥2.16;汇率 7.2;2026-09-01 官网价)
6. `scripts/zen-usage-ledger.py`:读 stats.zen 周 tokens × rates → append_ledger(estimated=true,幂等,--dry-run)
7. **不做(另立)**:dsh provider 接线(003 并行会话未提交改动在同文件,回避冲突,backlog 登记);Anthropic↔OpenAI 翻译层(claude 兜底);Zen 硬现金闸

## Checkpoints

- `cd /d/Tool && node --test test/relay-*.test.js` 7 绿(含活集成)
- `pytest tests/orchestrator/test_gateway.py tests/orchestrator/test_zen_ledger.py` 11 绿
- 生产 relay 重启后:`/__status` 双 kimi + routes.zen;实测 /zen/chat/completions 200;`/__stats` zen 独立计数且 kimi 水位不变
- zen-usage-ledger.py --dry-run 打印估算金额

## Rollback

- relay:删 ZEN/proxyZen/路由行 + 重启 → 纯双 kimi;opencode.env 留文件无影响
- ai-factory:rates/脚本/文档为纯增量;gateway.py 过滤对无 zen 场景等价原逻辑
- Zen 余额已充 $30:测试消耗 < $0.01;余额在 Zen 侧,不受代码回退影响
