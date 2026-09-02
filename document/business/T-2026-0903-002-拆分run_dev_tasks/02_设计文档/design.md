# 设计:run_dev_tasks 拆分(复杂度 46→可维护)

- 工单:`pool/tickets/T-2026-0903-002.yaml`
- 阶段:P2 设计
- 类型:纯重构(行为零变化)

## Architecture

`run_dev_tasks` 退化为编排入口,五职责抽为私有函数。切分依据现状行号
(runner.py:192-356),每段职责自洽、返回值语义清晰:

```
run_dev_tasks(pool, ticket, adapter, project_dir, cfg, consult_adapter)  # 编排入口,cc≤10
  ├─ _lazy_load_tasks(pool, ticket, project_dir) -> str|None
  │     # 现状 L195-209:tasks.yaml 定位+装载;load_failed 挂起返回挂起串,否则 None
  ├─ _completion_or_deadlock(pool, ticket, project_dir) -> str|None
  │     # 现状 L210-221:无 ready 时——全 done→p4 转换(返回 p4/blocked 串),
  │     #   非全 done→deadlock 挂起;有 ready 返回 None(继续)
  ├─ _cost_gate_blocked(pool, ticket, cfg) -> str|None
  │     # 现状 L222-242:ds 日线+工单帽双闸(mingfang 降级 budget_warn);
  │     #   硬闸命中返回 blocked/suspend 串,放行返回 None
  └─ _dispatch_task(pool, ticket, task, adapter, project_dir, cfg, consult_adapter) -> str
        # 现状 L243-356:worktree/packet/retry_prompt/watchdog 执行+attempts 计数
        #   +入账+scope 越界+acceptance 复检+retry/consult/判负阶梯;返回终态串
        #   内部再抽 _verify_task(pool, ticket, task, result, wt) -> (verify, status, output)
        #   # 现状 L262-294:scope 越界检查+acceptance 复检,改写 result;使 _dispatch_task≤15
```

**行为保真的关键**:返回值字符串协议逐字保留,各分支返回点与原行一一对应:

| 原行 | 返回串 | 拆分后所在函数 |
|---|---|---|
| L208 | `suspended: 任务清单装载失败:…` | _lazy_load_tasks |
| L216/217 | `blocked`(门禁)/`auto: p4_verifying` | _completion_or_deadlock |
| L221 | `suspend: 依赖死锁` | _completion_or_deadlock |
| L231 | `blocked: ds 日现金线` | _cost_gate_blocked |
| L240 | `suspend: 工单预算帽` | _cost_gate_blocked |
| L305 | `task:{id}:done` | _dispatch_task |
| L311 | `retry:{id}:{attempts}` | _dispatch_task |
| L325 | `suspend: k3 配额超线` | _dispatch_task |
| L340 | `consult:{id}:{status}` | _dispatch_task |
| L348 | `suspend:{id}`(consult_exhausted) | _dispatch_task |
| L354 | `suspend: 任务判负` | _dispatch_task |
| L356 | `task_failed:{id}` | _dispatch_task |

编排入口逻辑:`_lazy_load_tasks` 返串即 return;`_completion_or_deadlock` 返串即
return;`_cost_gate_blocked` 返串即 return;否则 `task=ready[0]`,return `_dispatch_task(...)`。
注意 `_completion_or_deadlock` 需在 None 时同时给出 ready 列表(用返回元组或让
入口重算 ready_tasks——取后者,幂等无副作用,避免引入新数据结构)。

## How

1. **先锁行为**:跑现状 `pytest tests/orchestrator/test_gate_enforcement.py
   tests/orchestrator/test_statemachine.py tests/test_runner*.py -q` 全绿作基线。
2. 逐个抽出 `_lazy_load_tasks`/`_completion_or_deadlock`/`_cost_gate_blocked`/
   `_dispatch_task`(内含 `_verify_task`),**只移动代码不改逻辑**,注释随行。
3. `run_dev_tasks` 改为顺序调用三闸 + 派发,返回各闸非 None 串或派发结果。
4. 每抽一个函数即跑相关测试,保持绿;全部抽完跑全套。
5. radon 实测各函数 cc,`run_dev_tasks`≤10、辅助≤15;超标则进一步拆分。

## Checkpoints

- [ ] 拆分后 `radon cc runner.py`:`run_dev_tasks` cc ≤ 10,所有辅助函数 ≤ 15
- [ ] `pytest tests/ -q` 全绿(行为零变化)
- [ ] 返回协议:上表 12 个返回串逐字保留(grep 源码核对)
- [ ] 事件/台账:task_run/consult/budget_warn/usage_missing 字段与入账不变
- [ ] `run_dev_tasks` 公开签名 `(pool, ticket, adapter, project_dir, cfg=None, consult_adapter=None)` 不变
- [ ] ruff F 类零新增;`check_gate` 等其他函数零改动(diff 仅 runner.py 该函数段)

## Rollback

纯代码移动,无 schema/数据迁移。回滚 = revert 本单提交,恢复原上帝函数。
风险点:抽取时变量作用域/闭包捕获错误——由全套测试兜底(行为契约),
任一测试红即停止并修正,不带病前进。
