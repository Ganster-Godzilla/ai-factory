# AI Factory Plugin 设计文档

> **日期**:2026-07-25
> **状态**:设计已确认(用户逐节审阅通过)
> **形态**:Claude Code Plugin(方案 A)
> **版本管理**:本仓库(ai-factory)**不做 git 管理**(用户明确指示,2026-07-25)

---

## 一、背景与目标

### 1.1 起源

用户在 odoo18-e-manufacture 项目中已沉淀一套完整的"AI 协作架构":决策树流程(99-decision-tree.md,1400 行)、Phase 0-5 门禁、state.json/backlog 状态机、80 条分类记忆、8 个自动化脚本、自研 jenkins-mcp。该体系流程内容经过实战检验,但执行基板大量依赖"提示纪律"(指望模型每次自觉遵守),与 Claude Code harness 原生机制(Skills 渐进披露、Hooks 确定性拦截、Subagent 上下文隔离、Worktree 隔离、后台 Agent+Monitor 唤醒)存在系统性差距。

### 1.2 目标

1. **抽象**:将 Odoo MES 验证过的架构提炼为技术栈中立的 Claude Code Plugin,任何新项目安装即用
2. **升级**:把"提示纪律"规则迁移到 harness 原生强制机制(规则沿 E0→E3 阶梯晋升)
3. **回灌**(后续阶段,不在本范围):产出 MES 迁移指南,供 odoo18-e-manufacture 后续单独立项改造

### 1.3 已确认决策

| 决策点 | 结论 |
|---|---|
| 哲学框架 | 纳德拉成长型思维:系统是 learn-it-all,错误率随时间单调下降 |
| 推进路径 | 先抽象模板,再回灌 MES(本轮不动 MES 任何文件) |
| 套用对象 | 任意新项目,通用优先,技术栈中立 |
| 模板形态 | Claude Code Plugin(plugin.json + skills + agents + hooks + templates) |
| 版本管理 | ai-factory 目录不做 git 管理,不 init、不 commit |

---

## 二、现状架构盘点(Odoo MES,7 层)

| 层 | 产物 | 驱动方式 | 痛点 |
|---|---|---|---|
| 意图层 | proposals/ 生命周期(active/archived/obsolete)+ Phase 0-2 门禁 | 人工+决策树 | — |
| 流程层 | 99-decision-tree.md(12 章+5 附录)+ 7 个 .mdc 规则 | 每次会话靠模型记得去读 | 无触发机制,加载即上下文税 |
| 状态层 | state.json(模块 Phase/并发预算)+ backlog.md | 靠纪律手动更新 | 曾遗漏更新被指出 |
| 记忆层 | 80 条分类记忆(user/feedback/project/reference)+ 错误→memory 闭环 | 索引加载+相关性召回 | 闭环停在"记住",未机制化 |
| 工具层 | 8 个 ps1 脚本 + jenkins-mcp + archguard(已搁置) | 脚本散落 | agent 需被告知才调用 |
| 执行层 | 单主循环对话 + superpowers skills | 一切在一个上下文里跑 | 上下文压力大(开到 1M) |
| 监督层 | 每 Phase 人工门禁 + checkpoint-notify.ps1 | Human Dense | 每步需人在场 |

## 三、差距分析:提示纪律 → 确定性强制

| 现状机制 | Harness 原生机制 | 迁移方向 |
|---|---|---|
| 决策树靠"记得去读" | Skills 按触发条件渐进披露 | 1400 行手册 → 9 个技能+薄路由 |
| 25+ 条 feedback 记忆(如"推送前 pyflakes") | PreToolUse Hook 确定性拦截 | 事后记忆 → 事前预防 |
| state.json/backlog 靠纪律更新 | Stop Hook 自动校验 | 人工自觉 → 自动校验 |
| 单上下文硬扛(1M context) | Subagents(Explore/Plan/verify) | 上下文堆积 → 上下文隔离 |
| 并发会话共用仓库互踩 WIP | Worktree-per-proposal | 约定避让 → 结构隔离 |
| 门禁清单人工逐项核对 | gate-checker subagent + validate 脚本 | 人盯 → 机器查 |
| Human Dense 监督 | 后台 Agent + Monitor + PushNotification + Cron | 在场 → 唤醒规则 |

**核心洞察**:规则分布在"提示纪律 ↔ 确定性强制"光谱上,改造本质是把成熟规则推向强制侧。用户 2026-05 的 AI Factory 融合方案(附录 C)因当时工具不支持而冻结;harness 现有能力(后台 Agent、Workflow、Monitor、PushNotification)已追上该设计,解冻条件成立。

---

## 四、目标架构:6+1 层

```
L0 意图层 Intent      templates/(proposal/PRD/design 模板)     人类拥有决策权
L1 流程层 Process     skills/(10 个技能,触发式加载)          替代"记得去读"
L2 状态层 State       templates/(backlog/state) + sync 脚本    机器可读、自动校验
L3 记忆层 Memory      mistake-retro 技能 + 记忆分类约定         错误→机制孵化
L4 工具层 Tools       stack-profile.yaml + scripts/            技术栈中立的配置点
L5 执行层 Execution   主循环 + 只读子代理 + worktree 约定       上下文隔离
L6 监督层 Oversight   hooks(4 个) + 通知 + 并发预算            确定性强制
─────────────────────────────────────────────────────────────
横切:成长闭环(Growth Loop)  犯错→memory→清单→脚本→hook,规则只升不降
```

## 五、Plugin 目录结构

```
ai-factory/                              # d:\workspace\ai-factory(无 git)
├── .claude-plugin/
│   └── plugin.json                      # name: ai-factory, version, description
├── hooks/
│   └── hooks.json                       # §七 的 4 个 hook 注册
├── skills/
│   ├── ai-init/SKILL.md                 # 初始化项目骨架 + stack-profile
│   ├── phase0-proposal/SKILL.md         # Phase 0 提案
│   ├── phase1-requirements/SKILL.md     # Phase 1 需求分析 + 门禁
│   ├── phase2-design/SKILL.md           # Phase 2 方案设计 + 门禁
│   ├── phase3-implement/SKILL.md        # Phase 3 TDD 实现(委托 superpowers)
│   ├── phase4-verify/SKILL.md           # Phase 4 测试验证
│   ├── phase5-release/SKILL.md          # Phase 5 部署发布
│   ├── gate-check/SKILL.md              # 通用门禁检查,有权拒绝推进
│   ├── backlog-sync/SKILL.md            # 会话收尾回写 backlog/state
│   └── mistake-retro/SKILL.md           # §九 成长闭环
├── agents/
│   ├── gate-checker.md                  # 只读:干净上下文核查门禁产物
│   ├── backlog-keeper.md                # 只读:生成状态摘要(供 SessionStart)
│   └── mistake-auditor.md               # 只读:扫描近期 diff+错误,提议记忆/晋升
├── templates/
│   ├── stack-profile.yaml               # §六 配置模板
│   ├── backlog.template.md
│   ├── state.template.json
│   ├── proposal.template.md             # Phase 0
│   ├── prd.template.md                  # Phase 1
│   ├── design.template.md               # Phase 2
│   ├── rules-registry.md                # §五 规则登记表
│   └── gate-checklists/                 # 每 Phase 一张门禁清单
│       ├── phase1-gate.md
│       ├── phase2-gate.md
│       ├── phase3-gate.md
│       ├── phase4-gate.md
│       └── phase5-gate.md
├── scripts/
│   ├── init-project.sh                  # ai-init 调用(Git Bash)
│   ├── pre-push-check.sh                # 读 profile 跑 lint_cmd
│   ├── validate-state.sh                # Stop hook:代码变了 state 没动→警告
│   └── lib/                             # 公共函数(profile 解析等)
│       └── profile.sh
└── docs/
    ├── architecture.md                  # 本架构的使用者文档
    ├── adoption-guide.md                # L0-L3 采用路径
    ├── mes-migration-guide.md           # MES 回灌映射表(§十一)
    └── superpowers/specs/               # 本设计文档所在地
```

## 六、技术栈中立化:stack-profile.yaml

所有 hook/skill 不硬编码技术栈,只读项目根目录的 `stack-profile.yaml`:

```yaml
project:
  name: "项目名称"
  type: "简述"
stack:
  language: python                  # 仅声明,用于选择默认检查器
  lint_cmd: "python -m pyflakes {changed_files}"   # {changed_files} 为占位符
  test_cmd: "pytest tests/"
  typecheck_cmd: null               # 可选
vcs:
  branch_model: "feature→test"      # 或 "feature→main" / "trunk"
  protected_branches: [main]
ci:
  type: jenkins                     # jenkins | github | none
  trigger_ref: "mcp:jenkins"        # CI 触发方式引用
paths:
  requirements: "document/business" # Phase 1-5 正式产物根目录
  specs: "docs/superpowers/specs"   # 修订类 spec 目录
security:
  protected_paths: []             # 写操作需确认的路径片段,如 ["migrations/", ".env"]
budget:
  concurrent_max: 2                 # 同时 executing 的 proposal 上限
```

不同项目(odoo-wms / quant-ai-trading / 任意新项目)差异仅体现为不同 profile 值,架构同构。

## 七、Hooks 设计(E3 级,hooks/hooks.json)

| Hook 名 | 触发器 | 行为 | 失败语义 | 替代的旧纪律 |
|---|---|---|---|---|
| session-start | SessionStart | 调 backlog-keeper,注入 backlog 摘要+各模块 Phase+活跃 proposal(≤40 行硬上限) | 注入失败不阻断会话 | "会话启动读 backlog"记忆 |
| pre-push-lint | PreToolUse, matcher: Bash 且命令含 `git push` | 跑 stack-profile.lint_cmd(替换 {changed_files}) | lint 失败→**阻断** push | "推送前跑 pyflakes"记忆 |
| stop-state-sync | Stop | validate-state.sh:工作区有代码 diff 而 backlog/state.json 未变→警告注入 | 仅警告不阻断 | state 自动更新规则 |
| pre-write-protected | PreToolUse, matcher: Write/Edit | 命中 profile.protected 路径→要求确认 | 未确认→阻断 | (新增能力) |

实现约束:
- 全部用 Bash 脚本实现(目标环境 Windows + Git Bash,已有 block-pdf-excel-read.sh 先例)
- 脚本内通过 `${CLAUDE_PLUGIN_ROOT}` 定位插件资源
- profile 缺失时 hook 降级为不动作(打印提示),不得报错阻断

## 八、Skills 设计(流程层,10 个)

| Skill | 触发场景(description 关键) | 内容来源 | 与 superpowers 的边界 |
|---|---|---|---|
| ai-init | 新项目初始化、"套用 AI 架构" | 生成 CLAUDE.md/backlog/state/memory 骨架,交互式建 stack-profile | — |
| phase0-proposal | "我有个想法/新需求" | 决策树 §三+proposal 模板;只写想法/方向/范围 | brainstorming 之后、PRD 之前 |
| phase1-requirements | 写 PRD/功能清单/歧义澄清 | 决策树 §五+Phase1 门禁清单 | 需求分析产物模板化 |
| phase2-design | 方案设计/技术方案 | 决策树 §六+Phase2 门禁 | 与 brainstorming 产出对齐 |
| phase3-implement | 编码/TDD 实现 | 决策树 §七;**委托** superpowers:test-driven-development | 不重复造 TDD 轮子 |
| phase4-verify | 测试验证/黑盒 | 决策树 §八 | — |
| phase5-release | 部署/发布/合并 | 决策树 §九+附录 E | — |
| gate-check | 任何"推进/进入下一阶段"请求 | 读 profile+对应门禁清单逐项核查,**产物不齐有权拒绝**(固化 strict-phase-gate 刚性规则) | — |
| backlog-sync | 任务完成/会话收尾 | 回写 backlog 状态/进度/阻塞/决策 | — |
| mistake-retro | 犯错后/定期复盘 | §九 五问流程 | — |

每个 SKILL.md 遵循渐进披露:主文件 ≤200 行,门禁清单/模板按需引用。

## 九、成长闭环(mistake-retro 技能)

犯错后执行五问:

1. **根因是什么?** → 写入 memory(type: feedback)
2. **能否机制化?** → 能:产出 E2(脚本)或 E3(hook)草稿
3. **不能机制化的原因?** → 纯判断类规则,留 E1 并记录原因
4. **登记 rules-registry.md**,更新规则等级
5. **验证**:下次同类场景零复发;同一条 E1 规则被违反 2 次→强制晋升 E2/E3

规则强制等级定义:

| 等级 | 形态 | 示例 |
|---|---|---|
| E0 文档约定 | docs 规范 | 提交信息格式 |
| E1 提示注入 | CLAUDE.md/skill 指令 | "新需求先写 Proposal" |
| E2 脚本校验 | 可调用检查脚本 | validate-requirement |
| E3 Hook 强制 | 模型无法绕过 | push 前必跑 lint |

## 十、Agents 设计(只读,上下文隔离)

| Agent | 工具 | 职责 | 调用方 |
|---|---|---|---|
| gate-checker | 只读(Read/Glob/Grep) | 干净上下文对照门禁清单逐项核查,输出通过/不通过+缺失项 | gate-check skill |
| backlog-keeper | 只读 | 解析 backlog/state/proposals,生成 ≤40 行状态摘要 | session-start hook |
| mistake-auditor | 只读 | 扫描近期变更与错误记录,提议新记忆与规则晋升 | mistake-retro / Cron |

只读约束消除"自己查自己"的偏袒与上下文污染。

## 十一、采用路径与 MES 回灌

### 11.1 L0→L3 成熟度

| 级别 | 内容 | 适用 |
|---|---|---|
| L0 骨架 | 装插件→`/ai-factory:ai-init`→CLAUDE.md+backlog+state+profile(10 分钟) | 任意新项目 |
| L1 流程 | phase skills 生效 | odoo-wms 启动 |
| L2 强制 | 4 个 hooks 全开 | Odoo MES 回灌目标 |
| L3 自治 | 后台 agent+Monitor+Cron 唤醒规则(=AI Factory 附录 C 落地) | 3DWMS 复工试点 |

### 11.2 MES 回灌指南(docs/mes-migration-guide.md,本轮只产出文档)

映射表三类:
- 决策树章节 → 对应 skill(§八 已给出)
- 80 条 memory → E 等级建议(约 20 条可直接晋升 E2+)
- 现有 state.json/backlog/proposals → 模板兼容方案

**边界**:本轮不修改 odoo18-e-manufacture 任何文件;回灌作为后续独立立项。

## 十二、自测方案(模板自身的验收)

在 `d:\workspace\tmp\` 建 scratch 项目端到端验证(scratch 项目本身需 git init——验证 pre-push-lint 依赖 git 命令,这与 ai-factory 自身不做 git 管理不冲突):

1. `/ai-init` 初始化成功,stack-profile 生成且字段完整
2. 模拟完整 P0→P5 特性周期,各 phase skill 正确触发
3. 三个强制场景全过:
   - `git push` 被 pre-push-lint 拦截(lint 故意失败时)
   - 代码改动后 Stop,stop-state-sync 发出警告
   - Phase 1 产物缺失时请求推进,gate-check 拒绝

## 十三、风险与缓解

| 风险 | 缓解 |
|---|---|
| Windows 上 hook 兼容性 | 统一 Git Bash 实现;profile 缺失时降级不阻断 |
| SessionStart 注入膨胀成新上下文税 | ≤40 行硬上限,摘要由 backlog-keeper 生成 |
| 与 superpowers 技能触发冲突 | SKILL.md description 写清分工;phase3 明确委托 TDD |
| 规则过度强制打断心流 | 仅 lint push 为阻断级,其余警告级;晋升需违反 2 次触发 |
| 无 git 管理导致模板本身无版本轨迹 | 用户明确决策;docs/ 内文档头部标注日期与状态 |

## 十四、范围边界(本轮不做)

- 不修改 odoo18-e-manufacture、3DWMS、quant-ai-trading 任何现有文件
- 不做 git init / commit / push(ai-factory 目录)
- 不实现 L3 自治层(Monitor/Cron 唤醒)——仅在 adoption-guide 中定义
- 不迁移 archguard
