# PRD:create_incident 去重

## Why

007 雪崩实证:无去重自动建单 × 重试循环 = 看板被 9+ 张重复单淹没,真缺陷单被埋,boss 要解释。机制必须在源头收口。

## What

1. `orchestrator/daemon/incident.py`:`create_incident(pool, ticket, summary)`——已有未关闭 incident(related_ticket=原单 id)→ 复用(双方事件流留痕:incident 侧 incident_evidence,原单侧 incident_reused);否则新建(type=incident, related_ticket 回链,原单侧 incident_created)
2. deploy.py handle_deploy_failure 与 runner.py p5_releasing 判负路径统一改调 incident.create_incident
3. 单测三态:首建 / 复用(同 id 返回、事件追加、池子不增)/ 前单已关闭 → 允许新建

## 验收标准

- `pytest tests/orchestrator/test_incident.py` 等新测试全绿;全量 pytest 全绿
- 代码上 deploy/runner 不再各自直接 new_ticket 建 incident
- 007 场景回归:同一原单连续失败,池子中该原单的未关闭 incident 恒为 1 张
