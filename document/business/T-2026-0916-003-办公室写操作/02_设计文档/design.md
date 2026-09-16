# 设计:办公室阶段3(写操作)

- 工单:`pool/tickets/T-2026-0916-003.yaml`
- 阶段:P2 设计(实现后回填)

## Architecture

```
Sandbox.vue(待办面板/建单弹窗/产物芯片)
   ↓ fetch JSON
/api/v1/tickets/*  (app.py 新增,与 HTML 路由同 closure)
   ├─ approve/reject/resume → _apply_approve/transition/resume(statemachine)
   │    ├─ _check_fresh: base_ts vs _last_ts(读单事件文件) → 409 版本冲突
   │    └─ 写后 office.invalidate_office_cache()
   ├─ POST /tickets → new_ticket(pool .lock 协调) → draft
   └─ GET artifacts/<key> → project_dir_for + resolve ⊂ 项目目录 → send_file
```

## How

1. 抽取 `_apply_approve`(HTML 路由同步改用,单一事实源)。
2. JSON API 五个端点;`_check_fresh` 版本冲突(无 base_ts 不校验,兼容旧调用)。
3. Sandbox.vue:attention 面板(批准/驳回/恢复+同因强制)、建单弹窗、产物芯片+预览弹窗。
4. 测试 6 用例(批准+缓存失效/版本冲突/驳回两边/恢复/建单校验/产物+穿越)。

## Checkpoints

- [x] 批准 200+缓存失效;base_ts 过期 409 未执行
- [x] 驳回 p2→p1_drafting/其他→closed;恢复挂起↔非挂起 409
- [x] 建单 draft(created_by=human),未登记/空摘要 400
- [x] 产物 200;`../` 越界 404
- [x] 前端构建过;8321 端到端路由活性(400/404/SPA 新构建)

## Rollback

纯新增路由+前端组件,无 schema/数据迁移;HTML 路由行为不变(共用逻辑)。
回滚=revert 提交,沙盒回到只读。
