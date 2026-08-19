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
