# 设计 — T-2026-0829-006 任务分级快速通道(L1 现状 + L3 落地)

> 策略依据:`document/business/T-2026-0828-004-任务分级/02_设计文档/strategy.md`(权威,不复制)。
> 需求口径:`../01_需求分析/prd.md`(R1-R6)。本设计只写落法。

## Architecture

级别只有一个事实源:**`Ticket.level`**(yaml 单字段,缺省 L1)。三个决策点在消费侧读它,无新配置、无全局态:

```
Ticket.level (L1|L2|L3, load 兜底 L1)
   ├─ statemachine: 条件边守卫 + approval_target()  ← 流程长短
   ├─ circuitbreaker/runner: next_action(task, level) ← 熔断参数
   ├─ gates.check_gate: L3 裁剪分支                  ← 产物宽严
   └─ dashboard: 列表徽章 + 详情卡                    ← 可见性(只读)
```

L2 本单仅作为合法字段值存在,所有决策点对 L2 走 L1 路径(裁剪留后续单)。

## How

### R1 字段与建单(ticket.py, cli.py)

- `VALID_LEVELS = {"L1", "L2", "L3"}`;`Ticket.level: str = "L1"`(dataclass 默认值天然完成存量 load 兜底,与 p1_round 同模式)。
- `validate()` 追加:level 不在取值域 → problems 追加(走 save_ticket 拒入通道)。
- `new_ticket(..., level: str = "L1")`;CLI `orc new --level {L1,L2,L3}` 缺省 L1 保守。

### R2 状态机条件边(statemachine.py)

- TRANSITIONS 增两条:`p0_proposed → p3_queued {boss}`;`p5_releasing → done {release}`。
- `transition()` 在 actor 校验后加**级别守卫**(封闭两条边,写死在迁移表旁):
  `(frm,to) ∈ {(p0_proposed,p3_queued), (p5_releasing,done)}` 且 `ticket.level != "L3"` → IllegalTransition。
- L3 走 `p5_releasing→done` 时 `ev.setdefault("monitoring_skipped", True)`(策略:发布批准后即 done,事件留痕)。

### R3 审批解析单一化(statemachine.py, cli.py, app.py)

- 新增 `approval_target(ticket) -> str | None`:`p0_proposed` 态按 level 分叉(L3→p3_queued,否则→p1_drafting);其余态查既有 APPROVALS;非审批态 None。
- `cli approve` 与 dashboard `app.approve` 同改调它(L1/L2 返回与现字典完全一致,双入口同口径,R3 防漂移)。

### R4 熔断参数(circuitbreaker.py, runner.py)

- `next_action(task, level="L1")`:level=="L3" → `MAX_RETRY_L3=2`,attempts<2 retry,否则直接 suspend(**无 consult 分支**,策略:免会诊);其余 level 走现阶梯(≤3→consult≤1→suspend),行为零变化。
- `runner._fail_ladder` 调用点传 `ticket.level`;L3 永远不会进 consult 分支(next_action 不返回 consult),会诊后挂起段的 `reason_code="circuit_exhausted"` 路径复用现有。

### R5 门禁裁剪(gates.py)

- `check_gate` 开头加 L3 分支:`ticket.level=="L3"` 时——
  - `stage=="P3"`(p3_running→p4_verifying):**保留** task_verify_required 段(不可省四项之二:验收命令执行);
  - 其余所有 stage(P0/P1/P2/P4/P5_*):直接返回 `[]`(产物文件校验与 P4 verdict 一并豁免,verdict 由 QA 直跑 acceptance_cmd+事件承载)。
- 不可省四项的承载点逐项核对:发布批准=TRANSITIONS actor 表(不动);验收命令=P3 边 verify 留痕(保留);台账=ledger(不动);状态机迁移=transition 落事件(不动)。

### R6 Dashboard(views/templates)

- views 零改动(Ticket 对象已带 level)。
- `tickets.html`:表头加"级别"列,徽章分色(L1 灰/L2 蓝/L3 绿;L3 即快速通道标记,不另加图标列)。
- `ticket.html`:卡片区加"级别"卡:当前级别 + 副注(建单指定;存量单兜底 L1)。
- base.html 增 3 个 `.badge-l1/l2/l3` 样式(若无通用徽章类)。

## Checkpoints

- 每任务 acceptance_cmd = 定向 pytest + `echo Sx-OK`(见 tasks.yaml);TDD:先红后绿。
- S6 整单验收:`pytest tests/` 全量零红;`pyflakes` 改动文件零告警;`scripts/check-pool-load.py`、`scripts/check-complexity.py` 过闸。
- 演示路径自验:`orc new --level L3` 建单 → approve 落 p3_queued(L1 单同操作落 p1_drafting)→ L3 p5_releasing→done 事件含 monitoring_skipped;Dashboard 列表徽章可见。

## Rollback

纯增量:字段缺省 L1(存量行为不变)、新边仅 L3 可走(L1 走同边响亮报错)、熔断/门禁 L1 路径零变化。回滚 = revert 本分支;存量 76 单无需任何迁移。
