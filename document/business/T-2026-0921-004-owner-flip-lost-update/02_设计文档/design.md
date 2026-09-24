# T-2026-0921-004 设计:owner 翻转不落库(lost-update)根治

## Architecture

```
orchestrator/daemon/ticket.py:
  StaleTicketError        新异常:盘上指纹≠对象指纹(有人在我加载后写过)
  Ticket._disk_fp         私有字段(不序列化):load()/save() 时同步的文件指纹
                          (sha256 内容);save 后自更新=同对象连存不误伤
  ticket_lock(pool, id)   按票文件锁(沿用 _locked 的 O_EXCL 自旋范式;
                          锁文件 <id>.lock,超时 5s,用完即 unlink)
  save_ticket()           锁内:CAS 校验(盘上指纹≠对象指纹→StaleTicketError)
                          →校验→写盘→回写对象指纹。一切写路径自动过闸,
                          调用方零改动
orchestrator/daemon/statemachine.py:
  transition()            无需特改——save_ticket CAS 即 transition 的硬门;
                          frm 语义天然校验(盘上状态被改→指纹不符→拒)
orchestrator/daemon/runner.py:
  角色运行期存点          try StaleTicketError → 重载+事件 stale_aborted
                          +放弃本次写(boss 点击优先,runner 不抢)
orchestrator/dashboard/app.py:
  PID 锁(pool/.dashboard.pid):
    acquire:锁在且 PID 活→拒绝启动,打印占用 PID;
            锁在但 PID 死(孤儿已死)→回收启动,事件留痕
    release:atexit 清锁;活判 Windows=ctypes OpenProcess,POSIX=os.kill(pid,0)
```

## How

**F1/F2 CAS 硬门(ticket.py,红优先)**

- `Ticket.load()`:读盘后算 sha256 存 `_disk_fp`(dataclass 私有默认 None,
  `field(default=None, repr=False, compare=False)`,不随 save 序列化——
  asdict 排除下划线字段,序列化路径本就显式选字段,需核)
- `save_ticket(pool, ticket)`:
  1. `ticket_lock` 按票锁(锁内完成 2-4,TOCTOU 关窗)
  2. 盘存在且 `ticket._disk_fp` 非 None 且盘上 sha256 ≠ `_disk_fp`
     → `StaleTicketError(ticket_id)`(响亮,不合并不重试,裁定#3)
  3. 既有校验+写盘(原子:临时文件+replace,沿袭)
  4. 回写 `ticket._disk_fp` = 新内容指纹(同对象连存安全)
- 手动 new 的 Ticket(_disk_fp=None)首次保存:CAS 跳过(创建语义),
  保存后指纹就位,后续保存受闸
- 读路径(load_ticket/dashboard 只读)零影响

**runner 存点降级(O2 验收"正常路径不破"的另一面)**

- 角色运行周期 attempts/进度保存包 stale 处理:StaleTicketError →
  append_event(stale_aborted)+放弃该次写;不重载续跑(状态可能已被
  boss 翻走,续跑=越权)——响亮留痕,人/系统看事件决定
- _transition_gated 路径天然受 CAS 保护,无需特改

**F3 Dashboard PID 锁(app.py 启动钩)**

- `acquire_pid_lock(pool)`:`.dashboard.pid` 存在→读 PID→活判:
  活→`SystemExit(f"dashboard 已在运行(PID={pid}),拒启防孤儿")`;
  死→unlink+事件 `pid_lock_reclaimed`+继续
- 写入自 PID+启动时刻;`atexit` 注册 unlink(仅当锁内容=自 PID,
  防误删后启者)
- Windows 活判:ctypes OpenProcess(0x1000)→非 None 即活;
  POSIX:os.kill(pid,0)。双平台都有 fallback 语义测试

## Checkpoints

| 闸 | 判定 |
|---|---|
| O1 CAS | 两对象同载一票,先后保存→第二个 StaleTicketError,yaml 零污染 |
| O1b 连存 | 同对象 load→save→改→save 连续保存不误伤 |
| O2 行为不破 | orchestrator 全套件绿(批准/推进/挂起/恢复/runner 路径) |
| O3 PID 锁 | 活锁拒启(打印 PID)/死锁回收启动/退出清锁 三态齐 |
| O4 留痕 | stale_aborted/pid_lock_reclaimed 事件可查 |

## Rollback

- CAS 只在"真竞态"才拒(既往那是沉默损坏),回滚=去指纹比对三行;
  锁范式与 _locked 同源,无新依赖
- PID 锁故障兜底:删 .dashboard.pid 即可启(文档写入运维手册)
- runner stale 处理只增捕获,不改成功路径
