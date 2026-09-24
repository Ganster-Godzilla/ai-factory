# T-2026-0920-003 PRD:折源退场 + ChatGPT 接力 20x 组网

## Why

折源渠道 2026-09-20 判死(token 参水,不合作,模式一作废),relay 链路里
zy 备份必须摘除;同时 ChatGPT 20x 订位已开,组网接力复杂任务算力
(codex 双登录态+adapter 备用)。本票收口两件事的落地与留证。

## What

1. relay zy 链路摘除:gpt-6-astra 会话保持/zy-ds 回缺省/k2.6 摘除 zy 备份
2. ChatGPT 20x 组网:OAuth 登录+冒烟;通道=猫熊 VIP3 V365+TUN 常开;hosts fastfail 清理
3. codex 双登录态(CLI+VSCode)+codex adapter 备用(复杂任务给 GPT)
4. keys 册:凭证册密码不改,留观 2 周;折源 key 留档至 2026-10-04 到期清销

## 验收标准

| # | 场景 | 判定 |
|---|---|---|
| Z1 | zy 摘除 | relay 配置无 zy 备份路径,006 分级合 main |
| Z2 | ChatGPT 通道 | OAuth 登录成功+冒烟通过(2026-09-22 实证) |
| Z3 | 双登录态 | CLI 与 VSCode 两端可用 |
| Z4 | 凭证纪律 | keys 册密码不改;折源 key 留档期明确(至 10-04) |

## 范围边界

- 折源合作不复活(token 参水判死,不设复活条件外的人工复审)
- 组网只做 relay/CLI 层,不改编排器状态机
