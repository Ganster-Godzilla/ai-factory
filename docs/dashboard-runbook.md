# Dashboard 长驻化运维手册

> T-2026-1104-001 交付。Dashboard(8321)是工单审批与治理驾驶舱,必须"机器在即在"。

## 一键脚本

脚本:`scripts/dashboard-service.ps1`(仓内正本,替代旧 `pool/register-dashboard-autostart.ps1`)

```powershell
# 状态(随时可查,退出码 0=健康 1=异常)
powershell -NoProfile -File scripts/dashboard-service.ps1 status

# 注册(默认用户级=登录后拉起;-Admin 用计划任务=开机/无人登录)
powershell -NoProfile -File scripts/dashboard-service.ps1 register          # 用户级
powershell -File scripts/dashboard-service.ps1 register -Admin              # 计划任务(管理员)

# 手动控制
powershell -NoProfile -File scripts/dashboard-service.ps1 start
powershell -NoProfile -File scripts/dashboard-service.ps1 stop
powershell -NoProfile -File scripts/dashboard-service.ps1 unregister
```

## 拉起机制

- **用户级(默认)**:登录后由启动文件夹 `OrcDashboard.lnk` 拉起。
- **管理员级(-Admin)**:Windows 计划任务 `OrcDashboard`,AtLogOn 触发,崩溃自动重启(3 次/1 分钟)。
- 两种拉起均脱离拉起它的终端;关闭终端不掉线。
- 日志:`pool/dashboard.log`(cmd 追加,非 PowerShell 重定向)。

## PID 锁与真活判

- 单实例锁:`pool/.dashboard.pid`(JSON:`{pid, started_at}`)。
- 活判:Windows 必须 `OpenProcess` 成功 **且** `GetExitCodeProcess == STILL_ACTIVE(259)`;
  仅可打开句柄 ≠ 活着(僵尸对象可打开,11-04 实证)。
- 死/僵尸锁自动回收并记 `pid_lock_reclaimed` 事件。
- 已知残余风险:进程退出码恰为 259 时误判活(design Q3 裁定接受);如需更强,`status`/`start` 前加 8321 端口二次探活。

## 台账写入纪律(F7,防 BOM 事故)

凡写 `pool/tickets/*.events.jsonl`、`pool/ledger.jsonl` 必须 **UTF-8 无 BOM + `\n` 行尾**:

- **禁止** PowerShell `>` / `>>` / `Out-File`(默认 UTF-16LE 或带 BOM)写 jsonl。
- 允许:`Set-Content -Encoding utf8`(PS5.1 utf8 无 BOM)、`cmd /c ... >> log`、Python `open(..., encoding="utf-8")`。
- 外部工具写台账后若总览 404:检查首三字节是否 EF BB BF;读端已 utf-8-sig 容错(0c4c587),但写端回潮由 `test_events.py`/`test_ledger.py` 守卫钉死。

## 排错

| 现象 | 处置 |
|---|---|
| 启动报"已在运行(PID=xxx)"但 8321 不通 | PID 锁僵尸残留:`status` 确认后 `stop` 再 `start`;或删 `pool/.dashboard.pid` 后 `start` |
| 登录后 Dashboard 没起 | `status` 看锁/端口;`register` 是否已执行;查 `pool/dashboard.log` |
| 总览 404 但工单在 | 台账 BOM(见上);读端已容错,若仍 404 查 `pool/*.events.jsonl` 首字节 |
| 关窗/重启后需恢复 | `start` 一键拉起;`-Admin` 模式机器重启后自动起 |
