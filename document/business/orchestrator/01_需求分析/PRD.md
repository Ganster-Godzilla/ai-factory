# PRD-T-2026-0829-004: dsh 现金闸"明放"模式

> Phase 1 产物,源自 pool 工单 T-2026-0829-004(boss 2026-08-29 批准,决策"磨合期允许临时放开,但必须明放")。门禁:templates/gate-checklists/phase1-gate.md

## Why(问题与价值)

dsh 0.1.1-rc.2 不产出 usage trailer,G3 只交付了消费端。integration 分支 hotfix(a7de5d1)把硬契约降级为按 returncode 推进——方向对(硬判负卡死全部 dsh 角色,T-003 sre 实测),但实现是"瞎放":tokens={}、cost=0.0,`_record_cost` 对零值不入账,DS 日现金闸与单工单预算帽实质失明。

磨合期失败重试多,闸该松——但没有台账就回答不了"重试烧了多少钱""预算定多少合理",磨合期结束也无数据收闸。此外:integration 分支(T-2026-0828-003 已 done)8 个提交未合 main,已造成 p1_round 全站 500 事故一次;3 个旧契约测试红;USAGE_MISSING_MSG 文案与新行为矛盾。

价值:闸松得有数、偏斜彻底收口、测试回归绿色。

## What(范围与边界)

**做**:
0. **前置**:integration/T-2026-0828-003 合入 main(含降级、p1_round、G1-G8;boss 已批)。合后跑 check-pool-load + 全量 pytest 定基线(预期 3 红,由本单修)。
1. **估算入账**:adapter 降级路径按 `调用次数 × 单价`(orchestrator.yaml 新增 `budgets.ds_est_call_cny: 0.05`)入账;ledger 条目带 `estimated: true` 标记;`USAGE_MISSING_MSG` 改为与警告语义一致的文案。
2. **双闸 warn-only**:`ds_daily_exceeded` 与单工单预算帽超线时不阻断/不挂起,写 `budget_warn` 事件(含当前值/阈值)放行;orchestrator.yaml 标注 `mingfang_mode: true` + `review_after: 2026-09-12`(复审双触发:到期 or T-2026-0829-002 交付)。
3. **修 3 个红测试**:test_dsh_adapter 三例改为钉死新契约(按 returncode 推进 + usage_missing 留痕 + 估算入账)。

**不做**:
- 不做 session.jsonl.zstd 解析(真实用量归 T-2026-0829-002)
- 不动 k3 周配额闸(k3 有真实 usage,不受影响)
- 不改 dashboard 展示(estimated 标记已在 ledger,展示层后续需要再单独立项)
- 不恢复硬契约(明放是有意决策,复审时才评估)

## 非功能需求

- 估算单价/开关/复审日期全部走 orchestrator.yaml 配置,不写死代码;缺省值与现行行为对齐(闸默认仍硬,`mingfang_mode: true` 才降级 warn-only)。
- ledger.jsonl 只增字段不改格式,旧消费方(dashboard `_ds_month_cost` 等按 resource/unit 过滤)不受影响。
- 明放期间每次 dsh 调用必有台账行(零容忍记 0)。

## 验收标准

1. integration 合 main 后 `python scripts/check-pool-load.py` 全过;全量 pytest 基线=3 红(仅 test_dsh_adapter 三例)。
2. 降级路径(无 trailer):每次调用 ledger 恰增一行 `resource=deepseek, unit=cny, amount=0.05, estimated=true`;result 带 `usage_missing=True`;USAGE_MISSING_MSG 无"视同失败"字样。
3. `mingfang_mode: true` 时:日现金超线不再 "blocked",工单超帽不再 suspend,均写 `budget_warn` 事件并继续派发;`mingfang_mode: false`/缺省时恢复硬闸行为(向后兼容)。
4. 全量 pytest 绿(含改造后的 3 例),用例数非 0;pyflakes 过。
5. orchestrator.yaml 含 `mingfang_mode`/`review_after`/`ds_est_call_cny` 三键与中文注释。

## 歧义与开放问题
→ 见 [歧义澄清记录.md](歧义澄清记录.md)(4 条,全部经 boss 2026-08-29 决策)
