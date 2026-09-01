# 设计:create_incident 去重

## Architecture

`orchestrator/daemon/incident.py`(新,无环依赖:只 import ticket/events):
```
create_incident(pool, ticket, summary) -> Ticket
  ├─ 查 pool:related_ticket==ticket.id 且 type==incident 且 state∉{done,closed}
  │    → 命中:append_event(inc,'system','incident_evidence') + append_event(原单,'system','incident_reused',incident=inc.id) → return inc
  └─ 未中:new_ticket(type=incident, related_ticket=原单) + append_event(原单,'system','incident_created') → return 新单
```
deploy.create_incident 删除,改 `from orchestrator.daemon.incident import create_incident`(保持 deploy 内部调用名不变);runner.py p5_releasing 内联块删除,同 import 调用。

## How

1. incident.py + tests/orchestrator/test_incident.py(tmp pool 三态)
2. deploy.py:删 376-386 本地实现,顶部 import;runner.py:370-376 改调
3. 全量 pytest + check-pool-load;007 场景 grep 验证无其他 new_ticket(type="incident") 直调点

## Checkpoints

- 新单测 3 过;全量 pytest 绿;`grep -rn 'type="incident"' orchestrator/` 仅 incident.py 一处
- check-pool-load 0 bad

## Rollback

revert 合并提交即可(纯增量+两点调用);已复用的事件留痕不回删。
