# 采用路径(L0→L3)

| 级别 | 内容 | 前置 |
|---|---|---|
| L0 骨架 | 装插件 → `/ai-factory:ai-init` → CLAUDE.md/backlog/state/profile | 10 分钟 |
| L1 流程 | phase0-5 + gate-check + backlog-sync 技能生效 | L0 |
| L2 强制 | 4 个 hooks 全开(装插件即生效,验证见下) | L0 |
| L3 自治 | 后台 agent + Monitor + Cron 唤醒规则 | L2 + 团队接受度 |

## 各项目建议起点
- 全新项目:L0 → L1 直接到位
- 已有流程的项目(如 Odoo MES):先 L0 并存,按 mes-migration-guide 渐进替换到 L2
- 成熟项目试点自治:L3(需先积累 rules-registry 数据)

## 启用后手工验证清单(LLM 行为项,脚本测不到)
- [ ] 新会话启动时看到 backlog 摘要注入(≤40 行)
- [ ] 说"进入下一阶段"且产物缺失 → 被 gate-check 拒绝
- [ ] 故意改一个代码文件后结束回合 → 收到 state 未同步警告
- [ ] git push 且 lint 失败 → 被阻断,stderr 显示阻断原因
- [ ] 写 protected_paths 内文件 → 弹出确认
