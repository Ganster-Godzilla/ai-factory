# 技术方案: T-2026-1104-001 Dashboard 长驻化根治

> Phase 2 产物。门禁:templates/gate-checklists/phase2-gate.md
> 需求依据:`01_需求分析/prd.md`(F1-F7 / AC1-AC8);歧义裁定按 Q1/Q2/Q3/Q7 建议口径,Q4 不做修复工具。

## Architecture(结构与边界)

三件套，各自独立、互不依赖：

```
A. 进程长驻化(F1/F2)
   scripts/dashboard-service.ps1(入仓) ──注册/启动/停止/状态──► Windows 计划任务 OrcDashboard
        │                                                          │ AtLogOn + RestartOnFailure(3次/1min)
        │                                                          ▼
        └──────────────  一键调用  ◄────────────  powershell -NoProfile -WindowStyle Hidden
                                                          py -3.11 -m orchestrator.daemon.cli dashboard
B. PID 真活判(F3/F4)
   orchestrator/dashboard/app.py::_pid_alive_default
     Windows: OpenProcess(0x1000) 成功 → 再 GetExitCodeProcess == STILL_ACTIVE(259) 才算活
     POSIX : os.kill(pid,0)(不动)
   死/僵尸锁 → acquire_pid_lock 既有回收路径(unlink + pid_lock_reclaimed 事件)
C. 台账写手收口(F5/F6/F7)
   写端:orchestrator/daemon/events.py::append_event、ledger.py::append_ledger(已是 utf-8 无 BOM)
   守卫:tests 增 BOM 断言(首字节 != EF BB BF)防回潮
   纪律:docs/dashboard-runbook.md 记"PS 禁 > 重定向写 jsonl"
```

边界(不做):不动 Dashboard 功能面;不引 Windows 服务化(nssm/SCM);不批量改写存量台账;不改 deploy.py。

## How(关键实现)

### A. scripts/dashboard-service.ps1(新,入仓)

单脚本四动作,默认用户级(非管理员),`-Admin` 才用 Register-ScheduledTask(开机/无人登录):

| 动作 | 行为 |
|---|---|
| `register` | 首选**启动文件夹**写 `OrcDashboard.lnk`(WScript.Shell 创建快捷方式,目标=`powershell.exe -NoProfile -WindowStyle Hidden -Command "Set-Location D:\workspace\ai-factory; py -3.11 -m orchestrator.daemon.cli dashboard *>> pool\dashboard.log"`,工作目录=仓根);`-Admin` 改走 `Register-ScheduledTask -AtLogOn` 并迁移既有 pool/ 脚本内容入仓 |
| `unregister` | 删启动文件夹 lnk(或 Unregister-ScheduledTask) |
| `start` | 若 8321 未在听 → 启动(Start-Process 分离,日志重定向用 python 侧 logging 或 `cmd /c ... >> pool\dashboard.log 2>&1`,避免 PS `*>` UTF-16);已在跑则打印 PID 不重复 |
| `stop` | 读 `pool/.dashboard.pid` → 校验 PID 存活且命令行匹配 `orchestrator.daemon.cli dashboard` → Stop-Process;清锁 |
| `status` | 输出:8321 是否监听、池锁 PID、该 PID 是否存活、current release 目录;退出码 0=健康 1=异常 |

- **编码纪律**:脚本头部 `#requires -Version 5.1`;所有文件写用 `Set-Content -Encoding utf8`(PS5.1 utf8=带 BOM 仅限 .ps1 源码可接受;**绝不**用 `>`/`*>`/`Out-File` 默认编码写 jsonl/日志——日志由 cmd 追加或 python logging)。
- **幂等**:register 重跑=覆盖 lnk;start 重跑=单实例(活锁拒启由 app 层保证,脚本先查端口再决定是否拉起)。

### B. PID 真活判(app.py 改一处)

```python
def _pid_alive_default(pid):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.wintypes.DWORD()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    ...
```

- **259 撞码风险**(Q3):进程退出码恰为 259 的已死进程会被误判活。接受为已知残余风险并在 runbook 写明;若要更强,status/start 前可加 8321 端口二次探活——本波默认不做(需求 Q3 建议口径)。
- POSIX 分支保持 `os.kill(pid,0)`(CI 全 Linux,已有测试经注入 `alive_check` 覆盖)。

### C. 台账写手收口

- `append_event` / `append_ledger` 现状已是 `open(..., "a", encoding="utf-8", newline="\n")`——写端无 BOM。
- **新增守卫测试**(tests/orchestrator/):
  - `test_events_no_bom.py`:append_event 写两条后 `read_bytes()[:3] != b"\xef\xbb\xbf"` 且每条 json 可解。
  - `test_ledger.py` 增一例:append_ledger 后首三字节非 BOM。
- **审计结论**(F6):仓内写 `*.events.jsonl`/`ledger.jsonl` 的唯一路径即上述两函数(grep 已证,无第二写手);外部 BOM 来源=PowerShell 重定向,属纪律问题,由 runbook F7 收口。
- **读端容错**已落 0c4c587(utf-8-sig),回归用例 `test_overview_survives_bom_prefixed_events` 保留。

## 数据设计

无新表/新字段。仅文件:

| 文件 | 形态 | 说明 |
|---|---|---|
| `scripts/dashboard-service.ps1` | 新,入仓 | 一键脚本;首行 `#requires` + 注释含用法 |
| `pool/.dashboard.pid` | 现有 | 锁内容 `{pid, started_at}` 不变;真活判只改判定逻辑 |
| `pool/dashboard.log` | 新约定 | 计划任务/启动脚本重定向目标;PS 不重定向,改 cmd 追加或 python logging |
| `docs/dashboard-runbook.md` | 新 | 注册/启动/停止/状态/排错 + 写入纪律(F7) |
| 既有 `pool/register-dashboard-autostart.ps1` | 迁移后删除 | 内容并入 scripts/dashboard-service.ps1 -Admin 分支,pool/ 不入库故须迁出 |

## 接口契约

- **进程接口**:`scripts/dashboard-service.ps1 {register|unregister|start|stop|status} [-Admin]`;退出码 0 成功/1 失败;status 输出人类可读 + 机器可判(行首 `OK`/`FAIL`)。
- **锁语义**:`acquire_pid_lock` 对外契约不变(活锁拒启 SystemExit/死锁回收+事件);仅内部判定收紧。`release_pid_lock` 不变(只清自己的锁)。
- **编码契约**:凡写 `pool/tickets/*.events.jsonl`、`pool/ledger.jsonl` 必须为 UTF-8 **无 BOM**、`\n` 行尾;守卫测试钉死。
- **兼容**:Linux CI 的 POSIX 判活分支不变;既有测试全部经 `alive_check` 注入,不依赖真实进程,保持绿。

## Checkpoints(验证点)

| CP | 内容 | 验收命令/方式 |
|---|---|---|
| CP1 | 活判单测:注入 OpenProcess 成功但 GetExitCodeProcess≠259 → 判死;==259 → 判活 | `python -m pytest tests/orchestrator/test_dashboard_pidlock.py -q` |
| CP2 | 既有 PID 锁测试(拒启/回收/只清自己/损坏锁)全绿,无回归 | 同上 |
| CP3 | BOM 守卫:append_event/append_ledger 产物首三字节非 BOM | `python -m pytest tests/orchestrator/test_events.py tests/orchestrator/test_ledger.py -q` |
| CP4 | 脚本 lint/干跑:`status` 在干净机/锁缺失/锁存活三态输出正确退出码 | 手动 `powershell -File scripts/dashboard-service.ps1 status` |
| CP5 | 端到端:register→start→关终端→`curl 127.0.0.1:8321` 200→stop→status 非活 | 手动四步(发布/验收阶段实证) |
| CP6 | 全量 pytest 绿 + check-pool-load 0 bad + `orc guard pre-merge` PASS | `python -m pytest -q`;`py -3.11 scripts/check-pool-load.py`;`orc guard pre-merge` |

## Rollback(回滚方案)

- **代码**:`revert` 本单提交即回旧 `_pid_alive_default`(OpenProcess 裸判)与无守卫测试;僵尸拒启旧病复现风险已知,回滚仅应急。
- **脚本**:`scripts/dashboard-service.ps1 unregister` + 删除脚本;机器上已注册的计划任务/启动项一并清。
- **台账**:本单不改写存量 jsonl,无需数据回滚;新守卫测试随 revert 移除。
- **运行中 Dashboard**:回滚代码前 `stop` 脚本停实例,回滚后按旧方式(`orc dashboard` 前台)可起,功能不受影响。

## 测试用例设计映射

| 测试文件 | 新增/修改用例 | 对应 AC |
|---|---|---|
| tests/orchestrator/test_dashboard_pidlock.py | 僵尸(259 之外退出码)判死回收;真活(259)拒启;GetExitCodeProcess 调用失败(句柄无效)判死 | AC4 |
| tests/orchestrator/test_dashboard_pidlock.py | POSIX 分支保持(经注入 alive_check,既有用例) | AC5 |
| tests/orchestrator/test_events.py | append_event 产物首三字节非 BOM、逐行可 json.loads | AC6 |
| tests/orchestrator/test_ledger.py | append_ledger 产物首三字节非 BOM | AC6 |
| (手动/发布期) | dashboard-service.ps1 四动作 + 关终端存活 | AC1/AC2/AC3 |
| docs/dashboard-runbook.md | 写入纪律条款存在 | F7 |
