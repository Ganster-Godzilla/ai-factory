# ai-factory

双轨 AI 协作工厂:**编排器**(orchestrator/——工单、状态机、runner、adapter、台账)+ **技能包**(plugin/skills/——phase0-5 过程产物与门禁)。

## 双轨融合(R10,2026-08-29 定)

- **编排工单 = 系统账本**:凡产生代码/文档变更的任务,先建 pool 工单;产物挂 `ticket.artifacts`,门禁/状态变化写事件流,成本入台账。哪怕执行是交互式会话,工单也必须在。
- **技能包 = 过程闸**:`/ai-factory:phase0-proposal` → `phase1-requirements` → `phase2-design` → `phase3-implement`(TDD)→ `phase4-verify` → `phase5-release`;phase 间走 `/ai-factory:gate-check`(刚性,产物不齐禁止推进)。
- **执行 = 可替换**:适合自动化 → runner(k3/dsh adapter);需要 boss 在环决策 → 交互式。执行方式不影响工单与门禁的存在。
- **轻量例外**:纯问答、typo 级修改可免单,但须显式说明,不得默认免单。

## 纪律要点

- 规则登记与晋升:`.claude/rules-registry.md`(E1 自觉 → E2 检查脚本 → E3 hook 强制;同一 E1 违反 2 次必晋升)。
- 合 main 前必跑 `python scripts/check-pool-load.py`(R8:防数据-代码 schema 偏斜)。
- 配额/现金闸放开只许"明放"(R9):warn-only 标注磨合期+复审日期,台账照记可估算,禁止记 0。
- 测试:`pytest tests/`;lint:`python -m pyflakes {changed_files}`(stack-profile.yaml)。

## 布局

- `orchestrator/` 编排器(daemon/dashboard/adapters);`plugin/` 技能包与模板
- `pool/` 工单池(yaml + events.jsonl + ledger.jsonl);`document/business/` 需求产物;`docs/specs/` 设计
- `backlog.md` / `state.json` 进度看板与状态;`.claude/proposals/` Phase 0 提案
