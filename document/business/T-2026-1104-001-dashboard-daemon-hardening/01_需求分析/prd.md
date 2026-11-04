# PRD: Dashboard 长驻化根治(进程脱离会话 / PID 真活判 / 台账写手收口)

> Phase 1 产物。门禁:templates/gate-checklists/phase1-gate.md

## Why

Dashboard(8321)是工单审批与治理的唯一驾驶舱。2026-11-03/04 三连"自动关闭"实证,每次都要 boss 手动重启续命——审批中心随时可能不可达,治理动作直接停摆。三根因已锁定(均有代码/现场证据,非环境抖动):

1. **生命周期绑会话**:`orc dashboard` 前台常驻,拉起它的终端/会话一结束就陪葬(11-03 实证)。
2. **PID 锁假阳性**:`_pid_alive_default`(orchestrator/dashboard/app.py:30)在 Windows 用 `OpenProcess(0x1000)` + `CloseHandle` 判活——进程已退出但内核对象仍可打开的僵尸场景会误判"活着",`acquire_pid_lock` 于是直接 SystemExit 拒启(11-04 实证,须手工删 `pool/.dashboard.pid` 才解)。
3. **台账 BOM 放倒读端**:外部工具(PowerShell)向 `*.events.jsonl` 写入 UTF-8 BOM,总览 `_today_events` 解析抛 JSONDecodeError(ValueError 子类),恰被"工单不存在"404 处理器接住,整页装死成 404。读端已修(0c4c587:utf-8-sig 容错+回归用例),**写手侧尚未收口**。

价值:驾驶舱"只要机器在就必须在"——登录后自动拉起、崩溃自愈、不被脏台账放倒,把"手动重启续命"归零。

## What

三件套,范围 = ai-factory 编排器 dashboard 生命周期与台账写入纪律:

| # | 功能 | 说明 |
|---|---|---|
| F1 | 脱离会话拉起 | 计划任务(AtLogOn 触发器)+ 文档化一键脚本(注册/启动/停止/状态);脚本可重复执行,不依赖登记它的终端存活 |
| F2 | PID 锁真活判 | Windows 活判加 `GetExitCodeProcess == STILL_ACTIVE(259)` 才算活;僵尸锁自动回收并留 `pid_lock_reclaimed` 事件;POSIX `os.kill(pid,0)` 分支保持 |
| F3 | 台账写手收口 | 凡写 `*.events.jsonl` / `ledger.jsonl` 的路径统一 UTF-8 **无 BOM** + 回归守卫测试;外部工具写入口径写入 runbook |

边界(不做):

- 不做 Dashboard 功能面改动(审批中心/总览/泳道不动);
- 不引入 Windows 服务化重型方案(nssm/SCM 另行评估);
- 不改写历史台账内容(存量 BOM 现场已手术,不批量重写)。

## 功能清单

见同目录 `功能清单.md`(F1-F7,优先级 P0/P1/P2)。

## 非功能需求

- **可用性**:终端/会话关闭不掉线;机器重启+用户登录后 ≤1 分钟自动拉起;异常退出自动重启(≤3 次、1 分钟间隔,沿用现有计划任务设置)。
- **幂等性**:重复注册计划任务 = 覆盖更新;重复启动 = 单实例(活锁拒启);stop 后 status 如实反映。
- **兼容性**:Linux CI 走 POSIX 判活分支保持绿;既有 pytest 全量绿,不改公共契约。
- **安全**:仍绑 127.0.0.1;计划任务以当前用户身份运行,不提权;不写口令/密钥。
- **可观测**:一键 status 输出 PID/端口/存活/PID 锁一致性;拉起、回收、拒绝启动均有事件或日志留痕。
- **可维护**:脚本入版本库 + runbook;PowerShell 写文本一律显式 UTF-8(`Set-Content`/`Out-File -Encoding utf8`),禁止 `>` 重定向写 jsonl(PS 5.1 `>` 默认 UTF-16LE)。

## 验收标准

| AC | 内容 |
|---|---|
| AC1 | 经一键脚本启动后关闭终端/会话,8321 仍可访问(GET / 200),PID 不变 |
| AC2 | 计划任务可查询已注册;`Start-ScheduledTask` 手动拉起成功;登录触发口径文档化并实测(或 boss 机器重启后复核) |
| AC3 | stop 一键停止并清锁;status 可区分 running/stopped,并核对 PID 锁一致 |
| AC4 | 僵尸锁单测:pid 存在但已退出 → 回收启动 + `pid_lock_reclaimed` 事件;活进程仍拒启(不误杀) |
| AC5 | POSIX 判活分支单测保持绿(CI) |
| AC6 | 写手回归:append_event / append_ledger 产出文件首字节非 EF BB BF;外部 BOM 文件下总览不炸(0c4c587 用例保留) |
| AC7 | 仓内 jsonl 写入口径审计结论登记(无绕过 utf-8 的写手) |
| AC8 | 全量 pytest 绿 + check-pool-load 0 bad + `orc guard pre-merge` PASS |

## 歧义与开放问题

→ 见 `歧义澄清记录.md`(Q1/Q3/Q5/Q6 需 boss 裁定;其余给出建议口径待确认)
