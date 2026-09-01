# PRD:k3-c 第三账号入共享池

## Why

双账号周额度耗尽频发(zen-k3 兜底已启动过),第三账号是最便宜的扩容方式;key 已就位(D:\Tool\keys\k3-c.env)。

## What

1. relay failover 组:kimi1→kimi2→kimi3(k3-c)→zen-k3,前三个同语义轮询
2. 测试断言:__status backends 长度 2→4;kimi* 前缀水位过滤天然覆盖 kimi3
3. guide 密钥清单:k3-a/b + k3-c

## 验收标准

- node --test 全绿(4 后端断言 + zen-k3 翻译活集成套件)
- 钉选 kimi3:/v1/messages 200(新 key 真实可用)
- auto 模式:kimi1/2 冷却时优先 kimi3,zen-k3 仅在三者全冷却时承接
- check-pool-load 0 bad;.claude/rules 无新违例
