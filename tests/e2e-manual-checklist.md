# E2E 手工验证清单(LLM 行为项)

> 自动脚本(tests/e2e.sh)只覆盖 hook/脚本行为;以下项需在装好插件的真实会话中人工验证。

- [ ] 新会话启动 → 看到 backlog/state 摘要注入(≤40 行)
- [ ] 说"初始化项目" → ai-init 触发,交互式收齐 stack-profile 字段
- [ ] 说"我有个想法" → phase0-proposal 触发,产物落 .claude/proposals/
- [ ] Phase 1 产物缺失时说"推进" → gate-check 拒绝并列出缺失项
- [ ] 犯错被纠正后 → mistake-retro 提议记忆 + rules-registry 登记
- [ ] 改代码后结束回合 → Stop hook 警告 backlog/state 未同步
- [ ] lint 失败时 git push → 被阻断并显示原因
