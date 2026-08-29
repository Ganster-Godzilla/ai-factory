# 阶段产物与门禁口径标准(T-2026-0829-001)

> 数据权威源:`orchestrator/daemon/artifacts.py` 的 ARTIFACT_MANIFEST。
> 本文档是人读版说明,不维护清单副本;清单字段(路径/章节/内容/角色)以代码为准。

## 产物清单

P0–P5 全阶段产物一览(权威字段见 artifacts.py):

| 阶段 | 门禁边 | 产物 | 产出角色 |
|---|---|---|---|
| P0 | draft→p0_proposed | `document/business/<id>-提案.md` | pm |
| P1 | p1_drafting→p1_proposed | `<id>-prd.md` / `<id>-功能清单.md` / `<id>-歧义澄清记录.md` | pm |
| P2 | p2_designing→p2_approved | `docs/specs/<id>-design.md` / `<id>-tasks.yaml` | architect |
| P3 | p3_running→p4_verifying | 工单 yaml task["verify"] 留痕(无文件) | dev(系统) |
| P4 | p4_verifying→p5_ready | `docs/specs/<id>-验收报告.md` | qa |
| P5 | p5_releasing→monitoring | `docs/specs/<id>-发布记录.md` | release |
| P5 | monitoring→done | `docs/specs/<id>-观察窗报告.md` | sre |

## 技能流对齐

工单流(编排器自动执行)与技能流(plugin/skills 人机交互)定位不变,本标准只统一产物与门禁口径:

| 技能流(plugin/templates/gate-checklists) | 工单流(ARTIFACT_MANIFEST) | 差异 |
|---|---|---|
| phase0 提案(问题/方向/范围/不做) | P0 提案文档同四章节 | 零 |
| phase1 PRD(Why/What/验收标准)+功能清单带优先级+歧义记录 | P1 三件套同口径 | 零 |
| phase2 设计(Architecture/How/Checkpoints/Rollback)+任务切片 | P2 双产物+tasks 契约校验 | 零 |
| phase3 TDD 验收留痕 | task["verify"] 持久化 | 形态差异(事件流→工单 yaml) |
| phase4 验收报告 | P4 验收报告(环境/范围/用例结果/结论) | 零 |
| phase5 发布记录+观察 | P5 发布记录+观察窗报告 | 零 |

## 检查分级

- **机器判(gates.py 强制)**:产物存在、非空、必含章节(--require-section)、必含内容(--require-content,如"优先级")、tasks.yaml 契约(id 不重/依赖存在/无循环)、P3 verify 留痕。
- **人工判(human_checklist,审批人逐项)**:方向与范围成立、Why 成立、验收标准可判定、优先级合理、方案合理无未决开放问题、切片粒度合理、缺陷处置可信、回滚方案可执行、观察时长达标。

## 生效边界

- Ticket 新增 `created_at` 字段(建单 UTC ISO):**有字段=新单,全程新口径;无字段(None)=存量单,门禁旁路不追溯**。
- 不用工单号日期(天级粒度且跨天错位)、不回放事件流判定。
- 闸门挂载点:`transition()` 内 `_enforce_gate`(按 artifacts.manifest_for_edge 判定门禁边);cli/dashboard/runner 三入口统一覆盖。P0 门禁挂审批边界(p0_proposed→p1_drafting,draft 提交边不挂——draft 态无角色能产出提案)。project_dir 缺失=开发/配置错误(消息指到 orchestrator.yaml projects 登记);门禁未过:人工边 GateFailed(结构化 FAIL 行),runner 自动边转 suspend(reason_code=artifact_missing)+ gate_failed 事件。

### 已知边界(后续立案)
- 门禁读 project_dir 当前工作树:切换分支会影响判定(产物在工单分支上时,审批前需停在对应分支)。
- tasks.yaml 契约校验(P2)与执行(P3 lazy-load)间无快照绑定(TOCTOU),改文件不会复核。
- artifact_missing 挂起后 resume 会重跑角色(非幂等角色如 release 有重放风险);P3 verify 不合规的补救=核实后手改 yaml 或 closed。
- incident 事故单豁免全门禁(快速通道)。

## 观察窗

- 默认 24h;`orchestrator.yaml` `monitoring.window_hours` 为预留键(当前未接线,暂不可配)。
- 报告要素:观察窗(起止)/ 健康检查(结果)/ 结论;时长达标列人工复核项(不实现计时器)。
