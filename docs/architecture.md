# AI Factory 架构说明

> 设计规格:docs/superpowers/specs/2026-07-25-ai-factory-plugin-design.md(权威,冲突时以规格为准)

## 6+1 层

| 层 | 产物 | 机制 |
|---|---|---|
| L0 意图 | templates/(proposal/PRD/design) | 人类拥有决策权 |
| L1 流程 | skills/(10 个,触发式加载) | 替代"记得去读" |
| L2 状态 | backlog.md + .claude/state.json | 机器可读、Stop hook 校验 |
| L3 记忆 | .claude/memory/ + mistake-retro | 错误→机制孵化 |
| L4 工具 | stack-profile.yaml + scripts/ | 技术栈中立配置点 |
| L5 执行 | 主循环 + agents/(只读) | 上下文隔离 |
| L6 监督 | hooks/(4 个) | 确定性强制 |
| 横切 | 成长闭环 E0→E3 | 规则只升不降 |

## 规则强制等级
E0 文档约定 / E1 提示注入 / E2 脚本校验 / E3 Hook 强制。
同一 E1 规则被违反 2 次 → 必须晋升。登记处:.claude/rules-registry.md。

## Hook 失败语义
| Hook | 级别 | 行为 |
|---|---|---|
| pre-push-check | 阻断(exit 2) | git push 前跑 lint_cmd |
| validate-state | 警告(systemMessage) | 代码变了 backlog/state 没变 |
| pre-write-protected | 确认(ask) | 命中 security.protected_paths |
| session-start | 注入(≤40 行) | backlog/state 摘要 |

## 运行环境要求
- Git Bash(Windows)或任意 POSIX shell;`python` 在 PATH(hook 内 JSON/YAML 解析)
- python 输出已强制 `reconfigure(encoding="utf-8", newline="\n")` —— 不要移除,Windows 默认 cp936+\r\n 会污染 bash 管道

## 安装
本机/他机分发、项目级与全局启用、升级与卸载:见 [distribution.md](distribution.md)。
启用后 hooks 自动生效;skills 以 `ai-factory:<名>` 调用。

## 平台层(2026-08 新增)
本仓库同时是双 harness 编排器平台:根部 orchestrator/(守护进程)、pool/(运行时状态,gitignore)、orchestrator.yaml(平台配置)。插件库在 plugin/ 子目录,分发机制不变。设计规格:docs/superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md

### Dashboard(M4)
`orc dashboard` 启动 Flask 面板(默认 127.0.0.1:8321,仅本机;`--host` 可覆盖,局域网开放+认证属 v2 决策):

| 页面 | 路由 | 内容 |
|---|---|---|
| 总览 | `/` | k3 周水位(网关优先、不可达回退本地台账)、DS 今日/本月现金、待审批/运行中/挂起计数、今日事件按工单分组 |
| 审批中心 | `/approvals` | P0 提案 / P1 需求 / P2 设计 / P5 发布 / 探针草稿 / 挂起 六组;批准、驳回(P2 打回 P1 重做)、恢复均走状态机迁移(actor=boss,git 留痕) |
| 工单详情 | `/ticket/<id>` | 全字段 + 任务列表 + 事件流(倒序)+ DS 单票成本 + 产物指针 |

安全边界:工单 id 经 `ID_RE` 校验后才拼路径(堵 %5C 反斜杠路径遍历),非法 id 与不存在工单统一 404;页面不展示任何 key 信息。v1.1+ 留白:泳道看板、时间线、成本页、角色页。
