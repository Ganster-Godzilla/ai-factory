# 设计 — T-2026-0908-003 分流 T2

> 需求:`../01_需求分析/prd.md`(R1-R5)。前置:T-2026-0908-001(网关三通道)。

## Architecture

```
工单 level(006 字段)
  │ runner._driver_for_level(ticket): L2/L3→'k2.6',L1→None
  ▼ 两处 packet 注入:packet.model = driver or _model_for(cfg, role)
claude_code 适配器:packet.model ∈ DRIVER_MODELS{k2.6, gpt-6-astra} → claude -p --model <值>
  ▼ (其余 model 值一律不传,防 dsh 语义误注)
relay(T1 已上线):ROUTES['k2.6'] → zy-k2 链;缺省链本单 +zy-ds(glm 后 ds 前)
```

## How

### R1/R2 level→驾驶员(runner.py, claude_code.py)

- runner 新增 `_driver_for_level(ticket) -> str | None`:
  `return "k2.6" if getattr(ticket, "level", "L1") in ("L2", "L3") else None`
- `_dispatch_task`:`packet.model = _driver_for_level(ticket) or _model_for(cfg, "dev")`;
  `advance_once` 角色包:`model=_driver_for_level(t) or _model_for(cfg, role)`。
- claude_code.py:`DRIVER_MODELS = {"k2.6", "gpt-6-astra"}(relay 路由组键)`;
  `if packet.model in DRIVER_MODELS: cmd += ["--model", packet.model]`(其余值忽略,注释说明)。

### R3 zy-ds 入缺省链(D:\Tool)

- kimi-relay.js:zy-ds 条目**移到 ds-flash 正前方**并去掉 routeOnly;注释改为"R1 文本直切:
  同模型族免费通道,官方 ds-flash 留备份"。zy-k2/zy-gpt 保持 routeOnly。
- 缺省链变为 [kimi1-4, glm-flash, zy-ds, ds-flash, zen-k3];relay-routes.test.js 的
  defaultChain 期望、relay-zen.test.js 顺位期望同步更新;k2.6 路由组不动(已含 zy-ds 靠前)。

### R4 台账脚本(scripts/canary-report.py)

- 只读聚合,零写入。窗口缺省近 7 天(`--days N` 可调):
  - 工单段:遍历 pool/tickets/*.yaml + events.jsonl,取窗口内活跃单:
    id/level/type/state/驾驶员(level 映射)/任务数/一次通过率(attempts_total≤1 的 done 任务占比)/
    返工(attempts_total 合计-任务数)/consult 次数/suspended 次数
  - relay 段:GET http://127.0.0.1:8787/__stats(不可达→标注),列 zy-k2/zy-gpt/zy-ds/
    kimi 池合计/ds-flash 的 requests 与周 tokens
  - 控制台读数段:固定 4 行手填位(k3-a/b/c/d 剩余额度%,W1 每周抄一次)
- 输出 markdown 到 stdout(`--out <path>` 可落盘)。

### R5 guide 手册段(docs/orchestrator-guide.md)

新增"分流与 W1 金丝雀"小节:自动路由口径表(level→驾驶员→relay 落点);
交互式试 k2.6 姿势(`claude --model k2.6` 或 `ANTHROPIC_MODEL=k2.6`);
台账节奏(每晚 canary-report + 每周控制台读数);回退姿势(工单 level 改 L1 / relay /__use)。

## Checkpoints

- S1(relay):`node --test test/` 全绿;生产 relay 重启后缺省链八层
- S2(runner/adapter):`pytest tests/orchestrator/test_level.py tests/orchestrator/test_claude_code_adapter.py -q` 全绿(新增用例)
- S3(台账+手册):canary-report.py 对真实 pool 出表(含 006/T1 行);guide 段落存在
- S4(整单):`pytest tests/ -q` 全量 + node 全量 + L3 工单隔离池端到端(伪造 adapter 断言 --model k2.6 传递)

## Rollback

- relay:`cd /d/Tool && git revert <commit> + 重启`(zy-ds 回 routeOnly)
- runner/adapter:ai-factory `git revert <merge>`(level 注入消失,全部回现默认)
- 台账/手册:文档性,无需回滚
