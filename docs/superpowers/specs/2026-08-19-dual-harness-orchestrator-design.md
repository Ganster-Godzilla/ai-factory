# 双 Harness 编排器(Dual-Harness Orchestrator)设计规格

> 日期:2026-08-19
> 状态:已评审(brainstorming 逐节确认)
> 相关:[2026-07-25-ai-factory-plugin-design.md](2026-07-25-ai-factory-plugin-design.md)(插件库规格,本文档是其上层平台扩展)

## 0. 背景与目标

DeepSeek Harness(dsh)发布后,工作流具备双 harness 条件:

- **Claude Code + k3**(多模态,包月周配额):负责 P0-P2 需求/设计、黑盒出题、视觉级测试、熔断会诊
- **dsh headless + DeepSeek V4 Pro**(按 token 充值,廉价):负责 P3 TDD 开发、脚本级测试、发布、巡检

目标:便宜模型持续执行开发任务,贵模型持续产出需求与设计,人类只做审批。上方由自研编排器(Orchestrator)做唯一状态权威。

### 关键设计决策(讨论确认)

1. **编排器是唯一状态权威**。两个 harness 都是无状态执行器——被派发任务、产出产物、写事件日志,不持有流程状态。dsh 预览版的破坏性变更只影响执行层适配器,不波及流程。
2. **模型路由表在编排器**,不依赖 dsh 内置。路由粒度到"角色"(见第 1 节)。
3. **角色间零自由对话**。数字化角色团队的通信走产物(黑板模式),不走聊天。
4. **双资源经济模型**:k3 = 包月周配额(稀缺,需预留人工用量);DeepSeek = 现金充值(设帽即可)。
5. **载体**:单仓库 `ai-factory/`,仓库即平台顶层;插件库降级为 `plugin/` 子组件;编排器为根部组件。
6. **产物住项目里**:PRD/设计/代码写在各业务项目内,pool 只存工单元数据+指针;编排器从不直接写项目文件,一律由 harness 会话代写。

## 仓库拓扑

```
d:\workspace\
├── ai-factory\                    ← 唯一方法论仓库 = 平台顶层("工厂")
│   ├── orchestrator.yaml          ← 平台配置:阈值/水位线/projects 登记
│   ├── pool/                      ← 运行时状态(gitignore)
│   │   ├── tickets/T-xxx.yaml     ← 工单(状态权威)
│   │   ├── tickets/T-xxx.events.jsonl
│   │   └── ledger.jsonl           ← 双资源台账
│   ├── orchestrator/              ← 编排器 = 工厂的大脑
│   │   ├── daemon/                ← 状态机+调度+熔断(常驻进程)
│   │   ├── adapters/              ← claude-code / dsh 适配器
│   │   ├── dashboard/             ← 看板(轻量 HTTP,挂 daemon)
│   │   └── probe/                 ← 质检探针
│   ├── plugin/                    ← 插件库(现根部 skills/hooks/agents/templates 挪入)
│   │   ├── skills/ hooks/ agents/ templates/
│   ├── docs/  tests/
│
├── quant-lab\                     ← 业务项目("工地",ai-init 初始化)
│   ├── .claude/                   ← 插件启用
│   ├── backlog.md  .claude/state.json   ← 项目局部状态(编排器的镜像)
│   ├── stack-profile.yaml         ← 接入声明
│   └── .orc-worktrees/            ← 开发工位
└── tiktok-ecommerce-ai\           ← 同构
```

三层关系:**工厂(ai-factory)= 顶层**;orchestrator 决定谁干什么、盯成本;plugin 分发给项目、教 harness 怎么干活;具体项目是工地。一次性迁移:根部 skills/hooks/agents/templates 挪入 `plugin/`,已分发项目按 distribution.md 升级流程更新引用。

## 第 1 节:角色名册与通信协议

### 1.1 角色名册(v1 定稿,7 AI + 1 人类)

角色 = 人设 prompt + 模型路由 + 权限边界 + 负责的工单状态段。

| 角色 | 模型/harness | 负责段 | 权限边界 |
|---|---|---|---|
| 产品经理 PM | k3 / Claude Code | P0-P1 草稿、质检探针 | 只写工单和 `document/business/` |
| 架构师 | k3 / Claude Code | P2 设计、任务切片、熔断会诊 | 写 `docs/specs/`,不碰实现 |
| 开发 | DeepSeek / dsh headless | P3 TDD 实现 | 只动自己 worktree,protected_paths 禁入 |
| 测试设计师 | k3 / Claude Code | 黑盒计划、验收用例出题(P2 末/P4 前) | 只写测试计划/用例,不看实现(防泄题) |
| 测试执行 QA | dsh(脚本级)+ k3(视觉级) | P4 跑黑盒、出验收报告 | 只读代码+执行验收命令;视觉用例看不到实现 |
| 发布员 | dsh headless | P5 合并、部署 | 唯一能合 main 的角色,且需人工审批触发 |
| 运维 SRE | dsh 巡检 + k3 诊断 | P5 后观察窗、线上异常 | 只读监控+预定义回滚;异常开工单 |
| 老板 | 人类 | 全部审批门禁 | dashboard 按钮 / 改文件 |

**测试执行的双路路由**(黑盒不是只有脚本):
- 脚本级(API 断言、健康检查、Playwright 回放)→ dsh
- 视觉级(登录系统、走关键路径、截图判断)→ k3 多模态 + Playwright MCP
- 测试设计师出题时标注每用例 `executor: dsh | k3-vision`
- 黑盒的"黑"= 时间顺序(用例先于实现写出)+ 信息隔离(设计师读不到开发 diff)

### 1.2 通信协议(防瞎聊硬规则)

1. 角色间零直接消息。唯一通信:读黑板 → 执行 → 写产物 → 推进状态 → 追加事件日志。
2. 产物走模板契约(PRD 模板、设计模板、切片清单 schema、验收报告 schema),下游只消费模板化产物。
3. 熔断会诊是唯一"类对话":架构师收到失败任务包(描述+错误输出+diff),输出诊断报告(模板化)。
4. 新增角色 = 名册加行 + prompt 文件 + 路由表加条目,不改状态机。

## 第 2 节:工单生命周期与状态机

```
                        ┌─ 老板审批点(●) ────────────────────┐
                        ↓                                    ↓
draft → p0_proposed ──●→ p1_drafting → p1_proposed ──●→ p2_designing
       (PM 起草/探针)        (PM 写 PRD)                    (架构师设计+切片
                                                            +测试设计师出题)
                        ┌─ 老板审批点(●) ─────────────────────────┐
                        ↓                                         ↓
        p2_approved ──●→ p3_queued → p3_running → p4_verifying → p5_ready ──●→ p5_releasing
                          (调度器取单)   (开发,任务级)  (QA 黑盒)              (发布员,人工按钮)
                                                                              ↓
                                              done ←─ monitoring(观察窗,SRE 巡检)
                                                        ↓ 异常
                                                   suspended + 自动开事故工单

任意状态 ──→ suspended(熔断用尽/老板驳回/SRE 报警)→ 老板处置 → 回上一状态或关闭
```

规则:
1. 三个老板审批点:P0(值不值得做)、P2(方案对不对)、P5(合 main)。P1 不单设审批。
2. P2→P3 是 harness 切换点;调度器按并发预算取单。
3. P3 任务级子状态:`tasks: [{id, status, worktree, attempts, model, depends_on}]`,可并行任务并行派发。
4. monitoring 观察窗默认 24h(项目可配);异常 → 预定义回滚 + 挂起 + 生成 `type: incident` 工单。
5. 事故工单快速通道:从 p1 起步,仍过 P2/P5 审批。
6. 每次状态迁移追加事件日志;dashboard 时间线直接渲染。

工单 YAML 骨架:

```yaml
id: T-2026-0819-003
type: feature | incident
project: quant-lab
state: p3_running
owner_role: dev
priority: normal            # incident 默认 high
artifacts:                  # 产物指针,内容住项目里
  prd: document/business/T-003-prd.md
  design: docs/specs/T-003-design.md
tasks: [...]
budget: { token_cap: 500000 }
created_by: probe | human
```

**产物落位**:产物由 harness 会话写进目标项目(PM/架构师在 Claude Code 会话里写),编排器只记指针、从不直接写项目文件。

## 第 3 节:双 harness 适配器契约

统一接口(两适配器实现同一契约):

```
run(task_packet) → result
  task_packet: { role, prompt_file, workdir, artifacts_in[], artifacts_out[],
                 acceptance_cmd, budget, timeout }
  result: { status: done|failed|timeout, artifacts[], tokens, cost, log_path }
```

- **Claude Code 适配器**:`claude -p` headless;角色 prompt = 人设文件 + 工单上下文 + 产物模板。用于 PM/架构师/测试设计师/视觉 QA/会诊。在项目目录内运行,项目插件 hooks/skills 照常生效(特性,非负担)。
- **dsh 适配器**:`dsh --profile headless "<任务包>"`;退出码 0/1 → done/failed;stdout/stderr 落事件日志附件。用于开发/脚本级 QA/发布员/SRE 巡检。
- **任务包(task packet)**:任务描述 + 设计相关段落 + 验收命令 + TDD 强制指令 + worktree 路径。故意不给整 repo 上下文(省 token、防跑偏)。
- **worktree 隔离**:每开发任务独立 git worktree;验收通过才允许进集成分支;dsh 写崩最多损失一个 worktree。

## 第 4 节:质检探针(质量信号放大器)

定位:不是有想象力的产品经理,是拿测量仪器的质检员。功能检查+代码检查,放大已存在的质量信号。

**触发条件**(全部满足):
- 池中 draft/p0_proposed 工单 < 水位线(默认 3)
- 当日探针起草 < 日上限(默认 3)
- k3 配额水位健康(< 编排器上限线)
- 无 P3 任务在跑(探针优先级永远低于执行)
- 频率:每天一次(默认凌晨 2 点)+ 池空即扫,取先到者

**扫描信号**(k3 会话,逐项目):
1. backlog 缺口(长期 blocked/TODO)
2. 测试缺口(覆盖率/无测试模块)
3. 质量信号(git 热点文件、mistake-retro 错误模式)
4. 运维反馈(monitoring/事故工单暴露的系统性问题)

**防幻觉四道闸**:
1. **证据强制**:草稿必须携带 `evidence`(路径+行号/命令输出/git 统计);schema 校验不过直接丢弃。
2. **可复现性复检**:daemon 重新执行证据中的命令,结果对不上 → 丢弃 + 记 mistake-retro。零模型成本,确定性校验。
3. **类型白名单**:只允许测试缺口/技术债热点/错误模式复发/运维隐患;禁止功能创意类(不可验证,属人类专利)。
4. **驳回记忆反馈**:驳回原因进探针下次 prompt;连续 3 次被驳回自动停 7 天。

探针产出为 `draft` 状态,老板采纳才进 `p0_proposed`。

## 第 5 节:事件日志、熔断与双资源成本台账

### 5.1 Append-only 事件日志

每工单一个 `pool/tickets/T-xxx.events.jsonl`:

```json
{"ts": "...", "ticket": "T-003", "actor": "dev", "event": "task_failed",
 "task": "task-3", "attempt": 2, "model": "deepseek-v4-pro",
 "tokens": {"in": 82000, "out": 11000}, "cost_cny": 0.42,
 "evidence": "logs/T-003/task-3-attempt2.log", "detail": "acceptance_cmd exit 1"}
```

铁律:只追加不修改(纠错用 correction 事件);daemon 崩溃后从工单 YAML + 事件日志重建全部内存状态;dashboard 时间线原样渲染。

### 5.2 熔断阶梯

任务级:
```
失败 → dsh 换 prompt 重试(最多 3 次,烧现金)
     → 架构师会诊 1 次(k3 配额,输入=失败任务包)
     → 仍失败 → 挂起 → 工单 suspended → 等老板
```

工单级:
- 预算帽(工单 token_cap / 日现金线)触发 → 立即挂起
- P3 连续 3 个任务走到会诊级 → 整单挂起(大概率是设计/切片问题)
- P5 发布失败 → 自动回滚 + 挂起 + 事故工单

### 5.3 双资源成本台账

`pool/ledger.jsonl`(append-only),两个账本:

**k3 配额账**(按周滚动):
| 消费者 | 用途 | 上限 |
|---|---|---|
| 老板交互会话 | 日常使用 | 不限,预留 60% |
| 编排器 headless | PM/架构师/视觉 QA/会诊 | 周配额 40%,到线降级 |

降级顺序(配额紧张依次砍):探针 → 视觉 QA 抽检频率 → 会诊(仅 incident)

**DeepSeek 现金账**:每工单 token_cap(默认 ¥10 等值);每日现金线(默认 ¥30)到线停止派发新任务;月度累计进 dashboard。

**k3 配额可观测性降级方案**:编排器自身 headless 调用有完整 token 记录;老板交互式用量取决于 Claude Code 是否暴露用量接口——有则 daemon 定期拉取,无则静态预留比例,水位条只显示编排器侧。实现期验证。

### 5.4 治理

所有阈值集中 `orchestrator.yaml`,改阈值走 git 提交(可 review、可回溯);日志/台账每月归档到 `pool/archive/YYYY-MM/`。

## Dashboard(看板)

定位:文件状态的只读视图 + 审批按钮,不是第二个状态权威。轻量 HTTP 服务挂 daemon,服务端渲染,局域网多参与人可访问。审批双通道(改文件 / 点按钮)等价,事件日志记录审批人。

信息架构:

```
总览(首页)    k3 水位 / DS 现金 / 待审批数 / 运行中 / 今日事件摘要
审批中心      按类型分组:P0/P2/P5/探针草稿/挂起;内嵌产物预览,一键批驳
需求池        泳道看板+列表过滤;工单详情(产物/任务/事件流/成本)
时间线        全局事件流,按项目/角色/类型过滤,日志附件
成本台账      双账本流水,按工单/角色/日下钻,月度归档
角色与运行    各角色当前任务/产出统计/harness 健康度/daemon 状态/worktree 池
探针收件箱    待采纳草稿(附证据+复检结果)/已驳回(含原因)/学习记录
项目接入      stack-profile 列表/健康检查/并发预算/保护路径
设置          orchestrator.yaml 可视化编辑(改动仍 git 留痕)
```

建设节奏:v1 = 总览+审批中心;v1.1 = 需求池+时间线;v1.2 = 成本/角色/探针收件箱;最后 = 项目接入+设置(初期直接编 YAML)。

## 第 6 节:项目接入层

### 6.1 stack-profile.yaml 演化

新增字段全部有默认值,老项目不升级也可接入:

```yaml
orchestrator:
  enabled: true
  ticket_paths:
    requirements: "document/business"
    specs: "docs/superpowers/specs"
blackbox:
  healthcheck_url: null        # SRE 巡检
  vision_routes: []            # 视觉级关键路径
  env_start_cmd: null          # 黑盒前拉起本地环境
execution:
  worktree_pool_size: 2
  integration_branch: "main"
# 已有 budget.concurrent_max 作为全局调度输入
```

### 6.2 Worktree 池

- 位置 `<项目>/.orc-worktrees/`(gitignore),每任务一个 worktree
- 池化预创建/复用;合并后回收;失败任务现场保留 24h(会诊/人工检查用)
- 合并路径:任务 worktree → 工单集成分支(全量测试)→ P5 发布员合 main
- Windows 注意路径长度与文件锁;依赖安装走项目自身命令

### 6.3 状态写回 ai-factory(接缝规则)

编排器不动项目文件。项目内 backlog/state 同步靠:
- PM/架构师的 CC 会话在项目内跑,写完产物走 `backlog-sync` 技能回写(harness 自然行为)
- dsh 任务 prompt 模板含"更新 backlog 对应条目"指令
- daemon 兜底检查:状态迁移后若项目 backlog 未同步 → 生成待办提醒(下次 session-start hook 显示)
- 冲突规则:编排器工单为权威,项目 backlog 为镜像;镜像滞后只提醒不阻断

### 6.4 接入新项目

一步:项目内跑 `ai-init` + 项目路径登记进 `orchestrator.yaml` 的 `projects:`。

## 第 7 节:测试策略与里程碑

### 7.1 编排器自身测试

- **单测**:状态机/切片/熔断/台账,纯函数,pytest
- **契约测试(核心)**:FakeHarness(按脚本返回的假执行器)替代真 CC/dsh,跑通工单全状态机——编排器逻辑 100% 不依赖真模型
- **集成测试**:真 dsh headless + 真 `claude -p` 最小任务,标记 `slow`
- **探针复检**:构造证据不符的草稿验证丢弃机制
- 编排器自身开发走 ai-factory TDD 流程(dogfooding)

### 7.2 里程碑(按每晚 2-4h)

| 里程碑 | 内容 | 验收标准 | 预估 |
|---|---|---|---|
| M1 骨架 | 仓库重构(plugin/ 挪位)+工单 schema+状态机+FakeHarness+CLI 审批 | 假工单从 draft 走到 done,事件日志完整 | 3-4 晚 |
| M2 双 harness 打通 | CC adapter + dsh adapter + 切片派发 + worktree 池 | 真实小工单走通 P2→P4 | 4-5 晚 |
| M3 熔断与台账 | 熔断阶梯 + 双资源账本 + 预算帽 | 造失败任务验证全链路+成本记账 | 2-3 晚 |
| M4 Dashboard v1 | 总览+审批中心 | 浏览器完成 P0/P2/P5 审批 | 3-4 晚 |
| M5 探针 + SRE | 质量扫描 + 防幻觉四闸 + 观察窗 | 探针产出带证据草稿,复检能丢伪造 | 3-4 晚 |
| M6 Dashboard 补全 | 全菜单 | IA 完整可用 | 按需 |

### 7.3 风险清单

1. dsh Developer Preview 破坏性变更 → 适配器契约隔离;FakeHarness 保证测试不依赖真 dsh
2. `claude -p` 无头模式在 Windows 的权限交互 → M2 第一天验证,必要时 settings.json 权限白名单
3. k3 周配额可观测性 → M3 验证,无接口则静态预留
4. git 仓库初始化:ai-factory 当前非 git 仓库,M1 第一步 `git init`(审批留痕、阈值治理都依赖它)
