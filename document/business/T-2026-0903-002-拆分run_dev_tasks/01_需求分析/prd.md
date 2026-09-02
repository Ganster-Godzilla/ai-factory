# PRD:run_dev_tasks 拆分(复杂度 46→可维护)

- 工单:`pool/tickets/T-2026-0903-002.yaml`
- 阶段:P1 需求分析
- 类型:纯重构(行为零变化)

## Why

`runner.py:192 run_dev_tasks` 圈复杂度 46(F 级,全仓最高),97 语句/31 分支/
13 return,五职责塞一处(lazy-load/完工判定/双成本闸/任务派发/验收判负阶梯)。
它是所有 dev 工单执行的心脏——复杂度越高,改动越易引入边角 bug,且审查/排错/
测试都难以聚焦。当前无低级 bug(ruff F 类 0),但"改它"本身已成风险源。

不拆的代价:每次动这个函数都在 46 条路径里赌不碰坏别的;"老出事故"类边角
问题会持续在心脏地带滋生。

## What

把 `run_dev_tasks` 拆为职责单一的私有函数,`run_dev_tasks` 退化为编排入口。
**对外行为零变化**:同输入→同返回值/同事件/同台账/同工单状态变迁。

功能要点:

1. **抽 lazy-load**:tasks.yaml 定位+装载+load_failed 挂起 → 独立函数。
2. **抽完工/死锁判定**:全 done→p4 转换、无 ready 非全 done→deadlock 挂起。
3. **抽双成本闸**:ds 日现金线 + 工单预算帽(mingfang 降级 budget_warn)。
4. **抽任务派发+验收判负**:worktree/packet/retry_prompt/watchdog 执行、
   scope 越界检查、acceptance 复检、retry/consult/判负阶梯。
5. **复杂度达标**:`run_dev_tasks` ≤ 10,各辅助函数 ≤ 15(radon 实测)。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| AC1 | radon 测拆分后 | `run_dev_tasks` cc ≤ 10;各辅助函数 cc ≤ 15 |
| AC2 | `pytest tests/ -q` | 全绿(行为零变化硬证据) |
| AC3 | 返回字符串协议 | `task:*:done`/`retry:`/`consult:`/`suspend:*`/`blocked:*`/`auto: p4_verifying`/`task_failed:*` 逐字不变(dev-loop.sh 依赖解析) |
| AC4 | 事件/台账字段 | task_run/consult/budget_warn/usage_missing 等事件字段与入账语义不变 |
| AC5 | ruff F 类 | 零新增 |
| AC6 | 签名兼容 | `run_dev_tasks(pool, ticket, adapter, project_dir, cfg, consult_adapter)` 签名与返回类型不变 |
