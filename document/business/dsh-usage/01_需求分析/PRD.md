# PRD-T-2026-0829-002: dsh usage 生产端——会话文件解析补台账

> Phase 1 产物,源自 pool 工单 T-2026-0829-002(boss 2026-08-29 批准)。门禁:templates/gate-checklists/phase1-gate.md

## Why(问题与价值)

dsh 0.1.1-rc.2 不产 usage trailer,明放模式(T-2026-0829-004)按 ¥0.05/次估算兜底——估算终归是估算,复审(2026-09-12)需要真账。已实证:`~/.dsh/sessions/<转义workdir>/<session-id>/session.jsonl.zstd` 是多帧 zstd 追加日志,内含 `assistant/chunk` 的 `{"chunk":{"type":"usage","usage":{"inputTokens":N,"outputTokens":N,"cacheReadTokens":N}}}` 记录,每 step 一条、(turn,step) 唯一。真实用量就在磁盘上,只缺消费端。

价值:台账从"估算"升级为"真实",明放模式可如期关闭;同时恢复 G3 硬契约——双源(trailer/会话)都断才算失明。

## What(范围与边界)

**做**:
1. **会话定位与解析**(adapter 内):run 结束后定位 workdir 对应会话文件——按转义规则快路径 + 读 session 头 `cwd` 字段匹配兜底;stream 全帧解压;过滤 `chunk.time >= run_start_ms` 的 usage 记录,按 (turn,step) 去重取末条,汇总 input/output/cacheRead。
2. **成本估算**:费率表进 orchestrator.yaml(deepseek 默认 input ¥2/M、cache hit ¥0.5/M、output ¥8/M,官网标准价;glm 记 0 但记 tokens);cost=input×miss价+cacheRead×hit价+output×out价,estimated=False(真实计量)。
3. **优先级**:trailer 存在 → trailer 精确值;否则会话解析;双缺 → failed+usage_missing(恢复硬契约,boss 已决)。解析异常(文件锁/损坏/缺 zstandard)按"会话源不可用"落入双缺判定,不炸 run。
4. **tokens 口径**:归一 {"input_tokens","output_tokens"}(仅新鲜 input,cacheRead 不进 tokens 字段——k3 水位虚高教训);cacheRead 只参与 cost 计算。

**不做**:
- 不改 dsh 工具本身;不做 GLM 侧会话格式差异的实证(无 GLM 会话样本,按同构假设,格式不符时自然落入双缺+硬契约,后续真用上 GLM 再单独立项)
- 不动明放 warn-only 闸逻辑(T-004 已交付);历史 estimated=true 台账不回溯修正
- 不解析 reasoning/tool 记录(只要 usage)

## 非功能需求

- 解析失败永不影响 run 结果判定(try 包裹,异常→视为无会话源)。
- zstandard 为新增依赖,requirements 登记;缺失时优雅降级(双缺)。
- 费率全部配置化,改价不改码。
- 44 个存量会话文件(最大 ~1MB 压缩)全量解析 < 1s 量级,热路径只解析当次会话。

## 验收标准

1. 真实会话文件端到端:对存量某 workdir 跑一次解析,汇总值与手工核算一致(input/output/cacheRead 三数,按 (turn,step) 去重)。
2. 优先级链:trailer 在→trailer 值(estimated=False);无 trailer 有会话→会话值(estimated=False);双缺→failed+usage_missing,但已发生的调用按 est_call_cny 照估入账(estimated=True)——判负是流程处置,烧了钱必须见账(R9 禁记 0)。
3. run_start 过滤:同 workdir 旧会话的 usage 不混入当次计量。
4. 成本:给定费率表,含 cacheRead 的样本 cost 计算精确到 4 位小数;glm provider cost=0 且 tokens 照记。
5. 全量 pytest 绿(含 T-004 明放回归 18 例),pyflakes 净;`python scripts/check-pool-load.py` 过。

## 歧义与开放问题
→ 见 [歧义澄清记录.md](歧义澄清记录.md)
