# T-2026-0921-004 PRD:批准边 owner 翻转不落库(lost-update)根治

## Why

2026-09-21 03:19/05:44 两现:boss 在 Dashboard 点批准,状态翻了但 yaml
owner 仍为 boss → 工单提前亮审批桶+越权可点。
2026-09-24 根因定位(事件流实证):
- **直接原因**:四次事发批准事件均无 owner_flipped 字段(09-23 的批准
  事件都有)——点击打到了跑旧代码(无 0919-011 翻转逻辑)的 Dashboard
  **孤儿进程**(本机 uvicorn 孤儿双绑端口有前科,windows-uvicorn-orphan-port)
- **系统缺陷**:save_ticket 无并发保护——任何持旧对象的进程可静默回写
  覆盖新状态(lost-update);Dashboard UI 层有 _check_fresh 乐观锁,
  transition() 层没有;孤儿进程还能活着双绑端口抢流量
孤儿进程是诱因,沉默覆盖是病灶——只要病灶在,换个诱因事故还会复现。

## What

1. **transition() 并发硬门(CAS)**:按票文件锁内重载+期望状态校验——
   调用方持有的 ticket.state 与盘上不符即 StaleTicketError 响亮报错,
   沉默覆盖从此变事故而非事故温床;save_ticket 全写路径同锁
2. **Dashboard 单实例防孤儿**:启动 PID 锁活校验——锁被活进程持有即
   拒绝启动并打印占用者 PID;正常退出清锁;配合端口独占(Windows
   SO_REUSEADDR 双绑陷阱针对性设防)
3. **回归测试**:双写竞态(一进程批准一进程慢写)→ 后者必炸且 yaml
   不被污染;PID 锁占用 → 第二个实例拒启

## 验收标准

| # | 场景 | 判定 |
|---|---|---|
| O1 | CAS 硬门 | 持旧对象的 transition/save 响亮失败(StaleTicketError),盘上状态零污染 |
| O2 | 正常路径不破 | 既有批准/推进/挂起重试全链路行为不变(编排器测试全绿) |
| O3 | 单实例 | 活锁占用时第二实例拒启并打印占用 PID;死锁(进程已死)可回收启动 |
| O4 | 事件留痕 | CAS 拦截/锁回收均入事件流,可审计 |

## 范围边界

- 只改编排器(ai-factory/orchestrator),不碰 AI-Lab/内核
- 不做分布式锁/多机并发(单池单机语义不变)
- 不做 UI 层改造(既有 _check_fresh 保留,CAS 在更底层兜底)
