# 设计 — T-2026-0908-001 zheyuan 渠道三通道入网关

> 需求:`../01_需求分析/prd.md`(R1-R4)。改动只碰 `D:\Tool\kimi-relay.js` 与 `D:\Tool\test\`。

## Architecture

```
客户端(Claude Code / orchestrator / sk dev)
  │ POST /v1/messages {model: "k3"|"k2.6"|"gpt-6-astra"|...}
  ▼
kimi-relay.js
  │ pickBackends(model):ROUTES[model] ?? DEFAULT_CHAIN(现 BACKENDS 顺序)
  │   ROUTES = {
  │     'k2.6':        [zy-k2, zy-ds, glm-flash, ds-flash, kimi1..4, zen-k3],
  │     'gpt-6-astra': [zy-gpt, kimi1..4, zen-k3],
  │   }
  ▼ 逐后端 failover(冷却跳过,pinned 优先,语义不变)
  ├─ zy-k2   :透传,body.model 重写 kimi-k2.6(既有 L254 路径)→ coding.zheyuanzhixin.com/v1/messages
  ├─ zy-ds   :translate → coding.zheyuanzhixin.com/v1/chat/completions,model deepseek-v4-flash
  ├─ zy-gpt  :translate → 同上,model gpt-6-astra
  └─ 既有后端:kimi1-4 / glm-flash / ds-flash / zen-k3(链尾备份,全部保留)
```

## How

### R1 三后端(BACKENDS 追加,不插位)

```js
// T-2026-0908-001 分流 T1:zheyuan 免费渠道(合伙人账号;官方 key 全留链尾备份)
{ name: 'zy-k2',  base: 'https://coding.zheyuanzhixin.com',     keyFile: 'zheyuan-k2',  model: 'kimi-k2.6' },
{ name: 'zy-gpt', base: 'https://coding.zheyuanzhixin.com/v1',  keyFile: 'zheyuan-gpt', model: 'gpt-6-astra',       translate: true },
{ name: 'zy-ds',  base: 'https://coding.zheyuanzhixin.com/v1',  keyFile: 'zheyuan-ds',  model: 'deepseek-v4-flash', translate: true },
```

- zy-k2 无 translate → 走 `b.base + req.url` = `.../v1/messages`,body.model 经既有
  `else if (parsed && b.model)` 分支重写 kimi-k2.6(探活实证该端点原生可用)。
- zy-gpt/zy-ds translate → `b.base + '/chat/completions'`(与 ds-flash 同构)。
- keys 启动加载(`loadKey('zheyuan-k2'|'zheyuan-gpt'|'zheyuan-ds')`),已在位;
  stats 由 `BACKENDS.forEach` 自动初始化三新条目。

### R2 路由组

```js
const KIMI_POOL = ['kimi1','kimi2','kimi3','kimi4'];
const ROUTES = {
  'k2.6':        ['zy-k2','zy-ds','glm-flash','ds-flash', ...KIMI_POOL, 'zen-k3'],
  'gpt-6-astra': ['zy-gpt', ...KIMI_POOL, 'zen-k3'],
};
const pickBackends = (model) => {
  if (pinned) { 现逻辑不变 }
  const chain = (ROUTES[model] || BACKENDS.map(b=>b.name)).map(n => BACKENDS.find(b=>b.name===n));
  const up = chain.filter(b => !(state[b.name] > now));
  return up.length ? up : chain;   // 全冷却时仍返回全链(现语义:兜底试一遍)
};
```

- 调用点:`attempt()` 前 `const candidates = pickBackends(parsed && parsed.model)`。
- 缺省链 = BACKENDS 顺序(零变化,回归锁)。

### R3 熔断/翻译沿用

零新代码:FAILOVER_CODES/冷却分级/settled 守卫对三新后端天然生效;既有 node 测试全绿作回归。

### R4 冒烟(test/smoke-zheyuan.js,node:test 或独立脚本)

1. 隔离端口起 relay(PORT=18787)→ /__status 断言 10 后端;
2. `POST /__use/zy-k2` 钉住 → /v1/messages {model:'k2.6',max_tokens:8} 真实调用 → 200 且内容非空;
   同法钉 zy-gpt(model gpt-6-astra)/zy-ds(deepseek-v4-flash)各 1 次;
3. `POST /__use/auto` 复位 → model='k2.6' 请求 → /__stats 断言 zy-k2.requests≥1(路由落点);
4. model='k3' 请求 → kimi1.requests 增(缺省链回归,若 kimi1 冷却则链内任一 kimi*)。

## Checkpoints

- S1:`node --test test/relay-keys.test.js test/relay-routes.test.js`(名单 10 + 路由组/顺位)
- S2:`node --test test/`(全量回归)
- S3:`node test/smoke-zheyuan.js` 四步全绿 + 生产 relay(8787)重启后 /__status 十后端

## Rollback

`cd /d/Tool && git revert <commit> && wscript kimi-relay.vbs`(或直接重启 relay 加载旧代码——
旧文件先留 `.bak-0908` 副本)。改动纯追加:回滚后三新后端消失,缺省链与现行为完全一致。
