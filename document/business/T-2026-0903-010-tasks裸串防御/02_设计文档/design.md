# T-2026-0903-010 设计:tasks 裸串双层防御

## Architecture

两层防御,各守一段:

```
手写/旁路脏数据 ──► [L1 写入层校验] ──► 工单 yaml(必为 dict 契约)
                        │ 拒入 ValueError
存量/漏网脏数据 ──► [L2 展示层容错] ──► ticket.html 渲染 200(str 项降级显示)
```

- **L1 校验点位**:`orchestrator/daemon/ticket.py` 的 `save_ticket()`。
  选它而非装载处:save_ticket 是所有写入的唯一收口(transition / runner /
  手工脚本全走它),一处设防全覆盖;装载处(load_task_list)契约本就产 dict,
  重复校验无增益。最小侵入:save 前对 `ticket.tasks` 跑 `_validate_tasks()`。
- **L2 容错点位**:`orchestrator/dashboard/templates/ticket.html` tasks 循环。
  Jinja 内 `task is mapping` 判定:dict 走原渲染;str 项 id 列显示串本身、
  其余列 "-"。对齐展示层防御规则 R2(容错不 500,脏数据可见可诊断)。
- **契约不动**:tasks dict 字段(id/title/depends_on/scope/context/status/
  attempts/verify/...)不变;str tasks 是非法数据,L1 拒入、L2 仅为存量兜底,
  不做自动迁移。

## How

S1(L1):ticket.py 增 `_validate_tasks(tasks)`——None/空表放行;每项须
`isinstance(x, dict)` 且含非空 `"id"` 键,违例抛 `ValueError("tasks 契约违例:
每项须为 dict 且含 id,收到: ...")`。save_ticket 写盘前调用。

S2(L2):ticket.html `{% for task in tasks %}` 块改:
`{% if task is mapping %}` 原五行渲染;`{% else %}` 渲染
`<td>{{ task }}</td><td colspan="4" class="muted">非法任务项(非 dict),请修数据</td>`。
事件流/产物块不动。

S3(测试):tests/orchestrator/test_dashboard.py 增:
- `test_ticket_detail_str_tasks_200`:pool fixture 造 str tasks 工单 →
  client GET → 200,响应体含 "S1" 与 "非法任务项";
- `test_save_ticket_rejects_str_tasks`:save_ticket(str tasks)→ ValueError;
- `test_save_ticket_accepts_dict_tasks`:dict 列表正常落盘回读。

## Checkpoints

1. S1+S2 实现后手工冒烟:007/008 详情页 200 不回退;构造 str tasks 工单详情页 200。
2. `pytest tests/orchestrator/test_dashboard.py -x` 全绿(含 3 新用例)。
3. 全池扫描脚本复跑:无 str tasks(与修前一致)。

## Rollback

改动为纯增量(一个校验函数 + 模板一个 if 分支 + 测试文件新用例),
`git checkout -- orchestrator/daemon/ticket.py orchestrator/dashboard/templates/ticket.html tests/orchestrator/test_dashboard.py` 即整体回退;
无数据迁移、无契约变更,回退零残留。
