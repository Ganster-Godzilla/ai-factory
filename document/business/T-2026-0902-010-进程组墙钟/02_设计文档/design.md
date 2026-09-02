# 设计:runner 进程组墙钟看门狗(适配器无关)

工单:T-2026-0902-010。PRD:`../01_需求分析/prd.md`。

## Architecture

### 问题定型

角色超时帽挂在适配器内 `subprocess.run(timeout=)`(`orchestrator/adapters/claude_code.py:25`、
`dsh.py:150`):timeout 的计时与 kill 都由 runner(父进程)执行,**父死即无人限时**,
角色子进程成孤儿无限烧(009 release 游荡 2h、S6 孤儿链污染并发验收,教训档 #20)。
且 `subprocess.run` 超时只 kill 直接子进程,不杀进程树——父活着时孙进程也可能泄漏。

### 方案总形

新增 **`orchestrator/daemon/watchdog.py`**,在 runner 层对 `adapter.run(packet)` 做
上下文包装(**适配器文件零改动**,靠 runner 进程内对 `subprocess.Popen` 的局部补丁
实现拦截;runner 单线程同步调用,补丁生命周期=一次角色调用,无并发坑):

```
advance_once / run_dev_tasks / consult
        │
        ▼
with watchdog.guard(pool, ticket, role, task_id, timeout):   ← runner 三处接线
        │   ├─ patch subprocess.Popen.__init__:
        │   │    每个角色子孙进程 → 强制独立进程组 + 登记注册表
        │   └─ 惰性拉起 detached 看门狗 helper(独立于父进程生命周期)
        ▼
   adapter.run(packet)   ← 适配器原样,无感知
        │
        ▼
guard 退出:未超时的登记项标 closed;若 helper 已杀 → 结果改写 timeout 判负
```

三个组件:

1. **guard(上下文管理器,runner 进程内)**
   - 进入时:deadline = now + timeout + GRACE(GRACE=15s,保证父活着时
     `subprocess.run(timeout=)` 先触发,**看门狗不抢跑**,只做兜底);patch
     `subprocess.Popen.__init__`,对 guard 期间创建的每个子进程:
     nt 注入 `CREATE_NEW_PROCESS_GROUP`,posix 注入 `start_new_session=True`
     (调用方已显式设置时尊重原值),随后把 `{pid, deadline, ticket, task, role}`
     追加进本次 guard 专属的注册表文件。
   - 首个登记发生时惰性拉起 **看门狗 helper 进程**(detached,父死不灭)。
   - 退出时:还原 Popen;把本 guard 登记且仍 pending 的项标 `closed`(父正常收工,
     helper 见到即跳过);回查注册表,若本 guard 有项被 helper 标 `killed`,
     向调用方暴露 `killed` 标记。

2. **看门狗 helper(独立 detached 进程)**:`python -m orchestrator.daemon.watchdog <注册表路径> --parent-pid <pid>`
   - 拉起方式:nt `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB`
     (防 runner 被 Job Object 罩住时连坐);posix `start_new_session=True`。
     不继承句柄、不写 stdout,父死存活。
   - 0.5s 轮询注册表:对 pending 且 `now >= deadline` 的项**按组终止整棵进程树**
     (nt `taskkill /PID <pid> /T /F`;posix `os.killpg(pgid, SIGKILL)`),
     标 `killed`,并向工单事件流 `append_event(pool, tid, "system", "watchdog_killed",
     pid=…, wall_clock_s=…, task=…, role=…)`(事件自带 ticket 字段)。
   - **父活探测**(nt `OpenProcess` 句柄 / posix `os.kill(pid, 0)`):若父已死且被杀项
     对应 p3 任务,helper 直接把工单 yaml 中该任务标 `status=failed`、
     `last_error="watchdog_killed: 墙钟 Ns 到点(父死)"`——父死场景下没人替它判负,
     恢复时走既有 retry/consult 阶梯;父活则由 runner 侧判负,helper 不动工单
     (避免与 runner 的 save_ticket 写竞态)。
   - 全部登记项 resolved 即退出;硬上限 max(deadline)+120s 自毁,无常驻守护。

3. **runner 接线(`runner.py`,唯一被改的运行时文件)**
   - 新增私有包装 `_run_with_watchdog(pool, ticket, adapter, packet, role, task_id)`:
     `with watchdog.guard(...)` 内调 `adapter.run(packet)`;退出后若 `guard.killed`
     为真,把结果改写为 `HarnessResult(status="timeout", output="watchdog_killed: …")`,
     失败沿既有阶梯(重试≤3→会诊≤1→判负)走,**timeout 语义与适配器自报一致**。
   - 三处调用点全部换走包装:dev 任务(`run_dev_tasks`)、会诊(`ca.run(cp)`)、
     五角色路径(`advance_once`)。task_id 仅 p3 有,角色路径传 None。

### 为什么这样选型(对歧义澄清记录的回应)

- "父死不灭"的载体选 **detached helper 进程**而非线程:线程随父死,不满足需求;
  也不是常驻守护/系统服务(澄清记录红线)——helper 按 guard 拉起、事毕自毁。
- 墙钟数值 = `packet.timeout`(task.timeout/ROLE_TIMEOUT 既有分级)+ 固定 GRACE,
  **不加新分级、不改旧数值**;GRACE 只是让位间隔,不是新超时档。
- 终止方式 P0 = 单级强杀(taskkill /F / killpg SIGKILL),即可过验收;
  W5 分级终止(先礼后兵)**不进本单切片**,留后续工单(PRD 明示不阻塞上线)。
- 进程组同时修复"父活但孙进程泄漏"的次级洞:`subprocess.run` 超时只杀直接子,
  组残留由 helper 到点清扫——与既有超时语义不冲突,是纯补强的收尾。

### 边界(不做)

- 不动适配器(`orchestrator/adapters/*.py` diff 必须为零,P4 用 `git diff` 证)。
- 不包 `_run_acceptance`/git/deploy 等非角色子进程:本单只治"角色孤儿无人限时",
  验收链有独立超时且 009 实证污染源是角色进程。
- 不动适配器协议、角色提示词、状态机、台账口径。

## How

### 注册表格式

路径 `pool/watchdog/<ticket>-<task|role>-<epoch>.jsonl`(每 guard 一文件,
行一条 JSON):`{pid, pgid, deadline, ticket, task, role, status}`。
status ∈ pending / closed / killed。helper 原地重写文件更新 status;
全部 resolved 后 helper 删除文件退出,审计留痕在事件流不在注册表。

### 时序

- **父活+准时收工**:adapter 返回 → guard 标 closed → helper 见全 resolved 退出,
  零事件零副作用。
- **父活+超时**:`subprocess.run(timeout=)` 先炸,杀直接子,adapter 报 timeout
  (现状不变);GRACE 后若有组残留,helper 按组清扫(孙进程),写 `watchdog_killed`
  (pid=组根);runner 回查若见 killed 把结果定死为 timeout(与 adapter 自报同值,
  幂等)。
- **父死**:helper 到点按组终止 → `watchdog_killed` 事件(字段:pid/墙钟/工单/任务)
  → 探父已死 → p3 任务直标 failed(timeout 判负留痕)→ 下次 advance 走 retry 阶梯;
  非 p3 角色路径只留事件,状态由人工/既有挂起恢复流程处理(009 实证路径)。

### 平台分支

| 动作 | Windows(主力) | POSIX |
|---|---|---|
| 挂独立进程组 | `creationflags \|= CREATE_NEW_PROCESS_GROUP` | `start_new_session=True` |
| 按组终止 | `taskkill /PID <pid> /T /F` | `os.killpg(pgid, SIGKILL)` |
| helper 脱离父 | `DETACHED_PROCESS\|CREATE_NEW_PROCESS_GROUP\|CREATE_BREAKAWAY_FROM_JOB` | `start_new_session=True` |
| 父活探测 | `ctypes OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` | `os.kill(pid, 0)` |

### 测试形态(D5:失败打印 `FAIL: <子句>`)

- 父活场景单测:短命令过 guard 正常返回、注册表闭环、helper 退出、无事件;
  子孙泄漏清扫(guard 内拉起"shell + 孙 sleep",超时后组被清扫);
  killed→timeout 改写单测;进程组归属断言。
- **孤儿实证**:测试主进程拉起"假 runner"子进程(脚本:guard(timeout≈3s) 内
  subprocess sleep 300 后自身长睡),杀父(不杀树),等墙钟到点断言:
  (a) sleep 进程组已不存在;(b) 工单事件流出现 `watchdog_killed` 且
  pid/墙钟/工单/任务字段齐;(c) 工单任务被标 failed(timeout 判负)。
  任一不满足打印 `FAIL: <子句>`。
- 全角色路径冒烟:stub adapter + monkeypatch `watchdog.guard` 记录器,
  逐路径(advance_once 五角色 / run_dev_tasks dev / consult)断言调用均经包装;
  既有 tests/test_runner.py 全绿证明父活语义回归。

## Checkpoints

| 切片 | 内容 | 验收 |
|---|---|---|
| S1 | watchdog.py 核心(guard/进程组/注册表/helper 拉起与按组终止/事件/父死判负落盘)+ 父活场景单测 | `pytest tests/test_watchdog.py -x -q` |
| S2 | 孤儿实证测试(杀父+短墙钟+sleep,复现 009 游荡场景并验证回收与留痕) | `pytest tests/test_watchdog_orphan.py -x -q` |
| S3 | runner 三处接线 + killed→timeout 判负改写 + 全角色路径冒烟 + 父活回归 | `pytest tests/test_runner_watchdog.py tests/test_runner.py -x -q` |

整单收口(P4 复核项,机器+人工):`pytest tests/` 全绿;
`python scripts/check-pool-load.py` 0 bad;
`git diff` 证 `orchestrator/adapters/` 零改动。

## Rollback

- 纯增量:回滚 = 还原 `runner.py` 三处接线 + 删除 `watchdog.py` 与三个测试文件,
  无数据迁移、无 schema 变更;事件流只新增 `watchdog_killed` 事件类型,append-only
  不需清洗。
- 看门狗 helper 无安装态:事毕自毁+硬上限自毁,回滚后无残留进程需清理。
- 回滚后行为精确回到现状(超时帽只在父活时生效),风险即本单要消除的原风险,
  无新增回滚死角。
