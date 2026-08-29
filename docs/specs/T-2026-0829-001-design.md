# 设计-T-2026-0829-001: 阶段产物与门禁口径统一

> Phase 2 产物。对应 PRD:document/business/T-2026-0829-001-prd.md
> 总原则:**一份清单、一处定义、处处引用;门禁分级(机器判存在与要素,人工判语义);存量不追溯。**

## Why

工单流当前**零产物校验**(调研证实:EXPECTED_ARTIFACTS 仅有设计无实现,runner 全阶段"done 即推进"),与技能流全阶段规范(plugin/templates/gate-checklists/)脱节。本设计把技能流的产物口径移植并写死进 daemon 侧:单一事实源清单 + 迁移级闸门 + 角色提示词对齐。两流定位不变(工单流=自动执行,技能流=人机交互),只统一产物与门禁口径。

## Architecture

```
orchestrator/daemon/artifacts.py   ← 单一事实源:ARTIFACT_MANIFEST(P0–P5 全阶段清单)
        ↓ 引用
orchestrator/daemon/gates.py       ← check_gate():按清单逐件机器校验,产出 FAIL 行
        ↓ 接线(三入口,统一走 transition)
statemachine.transition()          ← 人工边(draft→p0_proposed / p2_designing→p2_approved)
runner.advance_once/run_dev_tasks  ← 自动边(p1/p3/p4/p5/monitoring)
orchestrator/roles/prompts/*.md    ← 角色提示词按清单改写(人读口径与机读口径同源)
```

关键决策:

| # | 决策 | 理由 |
|---|---|---|
| D1 | 清单定义于 `artifacts.py` 常量,角色提示词/闸门/文档均引用之,禁各自维护副本 | PRD 非功能需求"单一事实源" |
| D2 | 闸门挂在 `transition()` 内(GATED_EDGES 映射),而非各调用点分别检查 | cli/dashboard/runner 三入口天然全覆盖,无漏接风险 |
| D3 | 生效边界 = Ticket 新增 `created_at` 字段:无字段=存量单不套用新门禁,有字段=新单全程新口径 | 工单号日期仅天级粒度且跨天错位;事件 ts 需回放事件流;新增字段最显式可判 |
| D4 | 门禁分级:机器项(存在/非空/必含章节/必含关键词/tasks 契约/留痕字段)由 gates.py 强制;人工项(语义质量)以 human_checklist 形式存于清单,审批人逐项打勾 | PRD 开放问题 3:要素校验自动化边界需分级 |
| D5 | doccheck 扩展 `--require-content`(必含字面内容,规范化后子串匹配),支撑"功能清单带优先级"类要素 | 现有 --require-section 无法表达非标题要素 |
| D6 | P3 验收留痕持久化到 task["verify"](passed/failed),闸门直读工单 yaml,不回放事件流 | 事件 output[:500] 截断后证据易丢;工单 yaml 是状态权威 |

## 产物清单(权威数据以 artifacts.py 为准)

| 阶段 | 门禁边 | 产物 | 路径 | 产出角色 | 机器校验 | 人工项 |
|---|---|---|---|---|---|---|
| P0 | draft→p0_proposed | 提案文档 | `document/business/<id>-提案.md` | pm | 存在+非空+必含章节[问题, 方向, 范围, 不做] | 方向与范围是否成立 |
| P1 | p1_drafting→p1_proposed | PRD | `document/business/<id>-prd.md` | pm | 存在+非空+必含章节[Why, What, 验收标准] | Why 是否成立、验收标准可判定 |
| P1 | 同上 | 功能清单 | `document/business/<id>-功能清单.md` | pm | 存在+非空+必含章节[功能清单]+必含内容"优先级" | 优先级合理 |
| P1 | 同上 | 歧义澄清记录 | `document/business/<id>-歧义澄清记录.md` | pm | 存在+非空(无歧义也须显式写"无歧义") | 无 |
| P2 | p2_designing→p2_approved | 设计文档 | `docs/specs/<id>-design.md` | architect | 存在+非空+必含章节[Architecture, How, Checkpoints, Rollback] | 方案合理、无未决开放问题 |
| P2 | 同上 | 任务切片 | `docs/specs/<id>-tasks.yaml` | architect | 存在+非空+**必过 slicer.load_task_list 契约校验**(查重/依赖存在/循环依赖) | 切片粒度合理 |
| P3 | p3_running→p4_verifying | 任务级验收留痕 | 工单 yaml task["verify"] | dev(系统) | 全部任务 status=done;凡有 acceptance_cmd 的任务 verify=="passed" | 无 |
| P4 | p4_verifying→p5_ready | 验收报告 | `docs/specs/<id>-验收报告.md` | qa | 存在+非空+必含章节[环境, 范围, 用例结果, 结论] | 缺陷处置结论可信 |
| P5 | p5_releasing→monitoring | 发布记录 | `docs/specs/<id>-发布记录.md` | release | 存在+非空+必含章节[合并清单, 版本, 回滚方案] | 回滚方案可执行 |
| P5 | monitoring→done | 观察窗报告 | `docs/specs/<id>-观察窗报告.md` | sre | 存在+非空+必含章节[观察窗, 健康检查, 结论] | 观察时长达标(默认 24h,orchestrator.yaml monitoring.window_hours 可配) |

命名口径与技能流逐项对齐,差异为零(技能流"PRD.md/技术方案.md/测试报告"为通用名,工单流按 `<id>-` 前缀区分多工单并存,属布局差异非口径差异,既有 PRD 路径约定不变)。

## How

### M1 artifacts.py(单一事实源)
- `ARTIFACT_MANIFEST`:dict,键=阶段标识("P0"/"P1"/"P2"/"P3"/"P4"/"P5_RELEASE"/"P5_MONITOR"),值={gate_edge, artifacts:[{path(含 {tid} 占位), role, require_sections, require_content}], human_checklist:[...]};P3 无文件产物,artifacts 为空,另设 task_verify_required=True。
- 提供 `manifest_for_edge(frm, to) -> stage | None`(GATED_EDGES 反查)。

### M2 doccheck 扩展
- 新增 `--require-content STR`(append):规范化(换行/空白/全角空格容忍,与 require-section 同套规整)后做子串判定,缺失打印 `FAIL: 缺少内容 "X"`;exit 码语义不变。

### M3 gates.py(闸门)
- `check_gate(project_dir, ticket, to_state) -> list[str]`:按 GATED_EDGES 找阶段,逐件校验;每件失败产出一行 `FAIL: <产物路径>: <缺失要素>`;P3 额外查 task 留痕。
- **存量旁路**:`ticket.created_at is None` → 直接返回 [](不追溯)。
- tasks.yaml 校验:调 `slicer.load_task_list`,异常转 FAIL 行(契约校验从此前移到 P2 批准门禁;P3 lazy-load 保留作兜底)。
- 挂起码:`SUSPEND_REASON_CODES` 增 `artifact_missing`。

### M4 接线(transition + runner)
- `transition()` 增可选形参 `project_dir`;命中 GATED_EDGES 且新单时:project_dir 缺失即 IllegalTransition(开发错误);check_gate 返回非空 → IllegalTransition,消息含全部 FAIL 行(人工边)或由 runner 捕获转 suspend(reason_code="artifact_missing",事件记 gate_failed,missing 清单入事件字段)。
- runner 自动边(p1/p4/p5/monitoring 及 run_dev_tasks 内 p3→p4)统一传入 project_dir。
- run_dev_tasks 验收复检后将 verify 结果持久化 `task["verify"]`(scope 越界同样记 failed)。
- cli.py 与 dashboard/views.py 的审批/迁移调用点补传 project_dir。

### M5 Ticket.created_at
- dataclass 增 `created_at: str | None = None`;new_ticket 写 UTC ISO;旧 yaml 缺字段 load 兜底 None(与 p1_round 同模式)。

### M6 角色提示词改写(pm/architect/qa/release/sre)
- 每个提示词设"产物"段,逐件列出本角色产物路径(含 `<工单号>` 占位)与必含章节骨架,措辞与 ARTIFACT_MANIFEST 一致;pm 覆盖 P0 提案+P1 三件套(PRD 开放问题 4:p0 提案与 release 角色一并改写);architect 补设计门禁检查点说明;dev 无文档产物不改。

### M7 口径文档
- `docs/specs/T-2026-0829-001-artifact-standard.md`:人读版权威清单说明、与技能流逐项对齐表、机器/人工分级口径、生效边界规则(created_at 判定)、观察窗口径(默认 24h 可配);显式声明数据权威源为 artifacts.py,文档不维护清单副本。

## Checkpoints

| 验收标准 | 落实点 |
|---|---|
| AC-1 权威清单 | M1 + M7(对齐表差异为零或显式说明) |
| AC-2 提示词改写 | M6(每提示词含本阶段全部产物名,doccheck 机器可判) |
| AC-3 G2 逐件校验 | M3+M4(缺件阻断指明缺哪件;空文件阻断;齐全放行;pytest 构造三用例) |
| AC-4 要素口径 | M2/M3(PRD 三要素、tasks 契约、P3 留痕、P4 正式化;缺要素判失败并指出) |
| AC-5 存量不追溯 | M5(created_at 边界)+ M3 旁路,pytest 构造存量单推进不阻断用例 |

## Rollback

- 全部改动为新增模块(artifacts/gates)+ 增量接线(transition 可选形参、Ticket 可选字段),无破坏性变更。
- 回退 = revert 本单合并:存量单无 created_at 本就不受门禁影响;新单门禁随代码回退消失,已落盘产物文件保留不影响状态机。
- 提示词改写独立可回退,不影响闸门代码。

## 歧义澄清决议(对应 PRD 开放问题)

1. P0 提案路径 → `document/business/<id>-提案.md`(与 PRD 同目录,业务文档一处)。
2. 观察窗 → 默认 24h,`orchestrator.yaml` monitoring.window_hours 项目可配;报告要素=观察起止/健康检查结果/异常与处置/结论;时长达标列人工项(不实现计时器,超本单范围)。
3. 自动化边界 → 机器判:存在/非空/章节/关键词/tasks 契约/留痕字段;人工判:语义质量(D4 分级写入清单 human_checklist)。
4. 提示词覆盖 → pm/architect/qa/release/sre 全改;dev 不改。
