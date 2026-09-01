# 设计:k3-c 入共享池

## Architecture

failover 组:kimi1(k3-a) → kimi2(k3-b) → kimi3(k3-c,新) → zen-k3(翻译兜底)
水位:kimi* 前缀过滤(gateway.py)自动含 kimi3,150M 闸口径不变。

## How

1. `D:\Tool\kimi-relay.js` BACKENDS 在 kimi2 后、zen-k3 前插入:`{ name: 'kimi3', base: 'https://api.kimi.com/coding', keyFile: 'k3-c', model: null }`
2. `test/relay-keys.test.js` 断言 backends.length 2→4;`test/relay-zen.test.js` failover 组名单同步
3. guide「密钥与网关」清单加 k3-c
4. 生产:重启 relay → 钉选 kimi3 curl 200 → auto 恢复 → 事件/04/05 文档

## Checkpoints

- node --test 全绿;/__status 四后端;钉选 kimi3 200;auto 恢复主链路
- k3_effective_week_tokens 包含 kimi3 但仍只计 kimi*(zen-k3 不计)

## Rollback

BACKENDS 摘 kimi3 + 重启即可;k3-c.env 留文件无影响。
