# PRD:办公室阶段3(写操作:能看→能办)

- 工单:`pool/tickets/T-2026-0916-003.yaml`
- 阶段:P1 需求分析(实现后回填)

## Why

沙盒(Three.js 方块人)已接通真实工单数据,但**看到待办处理不了**:审批要跳老
dashboard、建单要敲 CLI、产物只能翻文件系统。办公室闭环"看团队推进→处理审批
→验收交付"缺"办"这一环。

## What

沙盒内直接完成写操作,全部经编排器既有合法入口,不新开状态语义:

1. **审批/驳回/恢复**:待你处理卡片直接批,走 `_apply_approve`/`reject`/`resume`
   (与 HTML 路由同一逻辑);写后 invalidate 缓存,下轮轮询即新。
2. **网页建单**:选已登记项目+填目标,提交 `new_ticket` 存 draft(不触发执行)。
3. **交付物入口**:按工单 artifacts 指针只读产物文件,路径越界拦截。
4. **版本冲突**:页面快照 base_ts 与当前最后事件不一致 → 409"数据已变化,请刷新"。

## 验收标准

| # | 场景 | 期望 |
|---|---|---|
| AC1 | 批准(含 base_ts) | 状态推进+缓存失效;base_ts 过期 → 409 且未执行 |
| AC2 | 驳回 | p2_designing→p1_drafting,其他→closed |
| AC3 | 恢复 | 挂起→resume_state;非挂起 → 409;同因可 force |
| AC4 | 建单 | 登记项目→draft(created_by=human);未登记/空摘要 → 400 |
| AC5 | 产物 | 项目内文件 200 可读;越界( ../ ) → 404 |
| AC6 | 写安全 | 全经 statemachine+save_ticket,前端零直改 YAML |
