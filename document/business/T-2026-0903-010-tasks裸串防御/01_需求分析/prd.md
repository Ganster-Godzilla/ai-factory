# T-2026-0903-010 PRD:ticket 详情页对裸字符串 tasks 零容忍

## Why

2026-09-03,T-2026-0903-007/008 工单详情页 500。根因:交互式执行手工"装 tasks"
把 `tasks: [S1, S2, ...]` 裸字符串列表写进工单 yaml,`ticket.html` 按 dict 契约渲染
`task.get("id")` → Jinja `'str object' has no attribute 'get'` → 500。
同一脏数据喂给 runner `ready_tasks()` 同样炸(按 dict 取 status/depends_on)。

数据当日已修(两单重建 dict + 回填 status/verify),但防御层裸奔:
任何会话再手写一次字符串 tasks,详情页与 runner 照炸,无测试兜底。

工单台账是编排器唯一事实源,展示层是 boss 唯一视窗——脏数据致 500 = 视窗黑屏
且无法自诊断,必须由系统层设防而非靠"记住别手写"。

## What

双层纵深防御:

1. **写入层拒入(快速失败)**:工单 tasks 落盘入口校验——每项必须为 dict 且含
   `id` 键,否则抛 `ValueError` 拒绝写入。事故挡在写入时,而非渲染时。
2. **展示层容错**:对齐展示层防御规则 R2(None 容错),`ticket.html` 渲染 tasks
   兼容 str 项:str 项显示 id=字符串本身,其余列 "-"。存量/旁路脏数据不再 500,
   看板可读、可诊断。
3. **回归测试**:
   - 裸字符串 tasks 工单 → `GET /ticket/<id>` 返回 200,页面含字符串 id;
   - 写入层校验单测:str tasks 写入被拒(dict tasks 正常通过)。

## 验收标准

1. 构造 tasks 含 str 项的工单,`GET /ticket/<id>` → 200 且响应体含该字符串;
2. 经校验入口写入 `tasks=["S1"]` → 抛 `ValueError`(或等价拒绝),写入 dict 列表成功;
3. `pytest tests/orchestrator/test_dashboard.py` 及新增单测全绿;
4. 既有工单(007/008/全池)详情页渲染不回退(全池 yaml 扫描无 str tasks 回归)。
