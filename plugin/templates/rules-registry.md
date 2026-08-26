# 规则登记表(Rules Registry)

> 等级:E0 文档约定 / E1 提示注入 / E2 脚本校验 / E3 Hook 强制。
> 晋升触发:同一 E1 规则被违反 2 次 → 必须晋升 E2/E3(/ai-factory:mistake-retro 执行)。

| 规则 | 等级 | 载体 | 录入日期 | 晋升历史 |
|---|---|---|---|---|
| push 前跑 lint | E3 | hook: pre-push-check.sh | init | — |
| 代码变更需同步 backlog/state | E3(警告) | hook: validate-state.sh | init | — |
| 会话启动注入 backlog 摘要 | E3(注入) | hook: session-start.sh | init | — |
| 保护路径写入需确认 | E3(确认) | hook: pre-write-protected.sh | init | — |
| Phase 门禁刚性 | E1 | skill: gate-check | init | — |
