# 设计:模型网关接入 OpenCode Zen 兜底

## Architecture

```
claude / 工具 ──► relay :8787 ──failover 组──► kimi1 (api.kimi.com/coding, k3-a)
                      │                        kimi2 (api.kimi.com/coding, k3-b)
                      │                        zen-kimi (opencode.ai/zen, opencode) ← 新增兜底
                      └─/__stats ──► gateway.py(只合计 kimi*)──► k3 周水位闸
zen-kimi 周 tokens ──► scripts/zen-usage-ledger.py × rates.opencode ──► ledger(estimated=true)
```

关键事实:Zen Anthropic 端点要求 `x-api-key` 头;relay tryBackend 本就同时注入 `x-api-key` + `Authorization: Bearer`(kimi-relay.js:69-70),协议零改动。`base` 不带 `/v1`,客户端 `/v1/messages` 透传拼接后命中 Zen;`model` 字段触发既有 model 重写(kimi-relay.js:131),把 claude 模型 id 改写为 Zen Kimi id。

## How

**D:\Tool(relay 仓,main):**
1. `keys\opencode.env`:`KEY=TODO-FILL` 占位,用户手填真实 key(loadKey 缺 KEY 行 fail-fast)
2. `kimi-relay.js` BACKENDS 追加:`{ name: 'zen-kimi', base: 'https://opencode.ai/zen', keyFile: 'opencode', model: '<Zen Kimi id>' }`;模型 id 以 `curl https://opencode.ai/zen/v1/models -H "x-api-key: <key>"` 实测为准
3. `test\relay-zen.test.js`:`/__status` 三后端;钉选 `/__use/zen-kimi` 后断言请求落 zen base 且 model 被重写(拦截 https.request);存量测试不动

**ai-factory(feature 分支合 main):**
4. `orchestrator/daemon/gateway.py`:合计时过滤 `name.startswith("kimi")`;docstring 注明 zen 等付费兜底不计入共享池水位
5. `tests/orchestrator/test_gateway.py`:fake /__stats 加 zen-kimi 断言不计;补"仅 zen 后端时水位 0"
6. `orchestrator.yaml`:rates.opencode(input_per_m 4.3 / output_per_m 21.6 / cache 0,注释 $0.60/$3.00、汇率 7.2、2026-09 价);budgets 注释 zen 不占 k3 预算
7. `scripts/zen-usage-ledger.py`:读 /__stats zen-kimi 周 tokens × rates → append_ledger("opencode", amount, "cny", estimated=true);支持 --dry-run;配 pytest(假 stats + tmp pool)

## Checkpoints

- `cd /d/Tool && node --test test/` 全绿
- `pytest tests/` 全绿 + `python -m pyflakes` 改动文件 + `python scripts/check-pool-load.py`
- 重启 relay(vbs)后 `/__status` 三后端;钉选 zen-kimi 实测 /v1/messages 200;`/__stats` zen-kimi 周 tokens 增长
- k3_effective_week_tokens 不含 zen;zen-usage-ledger.py --dry-run 有 estimated 条目
- claude -p 经 relay 真实调用成功

## Rollback

- relay:BACKENDS 删第三项 + 重启(vbs)→ 回到双 kimi 语义;opencode.env 留文件无影响
- ai-factory:gateway.py 过滤在无 zen 后端时行为等同原逻辑,向后兼容;rates/脚本为纯增量,回退 = revert 合并提交
- Zen 侧已扣余额不可退 → 验证阶段只用最小 prompt
