# 设计:resume 同因幂等提示(防确定性 bug 连撞)

- 工单:`pool/tickets/T-2026-0902-016.yaml`
- 阶段:P2 设计
- 关联:R12;溯源 T-2026-0902-011(三连挂)/ T-2026-0902-014(incident 复用三次)

## Architecture

在**唯一 resume 收口**(`orchestrator/daemon/statemachine.resume`)入口加同因检测,
CLI 与 dashboard 两个调用点共用,天然语义一致(不各写一份)。复用现有
`IllegalTransition` 拦截路径(cli/dashboard 均已 except 它),无需新异常类型。

```
cli.resume / dashboard./resume/<id>
  └─ statemachine.resume(pool, t, actor="boss", force=False)   # 【+force 参数】
       ├─ 既有校验:state=="suspended" 且 resume_state 非空
       ├─ 【新增】同因检测(force=False 时):
       │    last_reason = 事件流最近一次 suspended 的 reason_code
       │    cur_reason  = t 当前(本次挂起)的 reason_code
       │       —— 同一事件:resume 前工单仍是 suspended,最近一条 suspended 即本次
       │    需比对"上一次":取事件流中**最近两条** suspended,
       │    若存在更早一条且 reason_code 与本次相同 → 同因
       │      → 抛 IllegalTransition("上次同因(<code>)挂起,根因未变;
       │         确认已修请加 --force / 勾选确认")
       └─ force=True 或无更早同因 → 走原逻辑,append_event 补 forced 标记
```

数据来源:事件流 `read_events(pool, t.id)` 过滤 `event=="suspended"`,取其
`reason_code`(suspend 已写此字段,statemachine.suspend L107-109)。

关键设计决策:
- **检测逻辑全部在 statemachine.resume**,签名加 `force: bool = False`(默认 False
  保持现行为);cli 加 `--force` 透传,dashboard 加确认勾选(表单字段)透传。
- 同因且未 force → 抛 `IllegalTransition`,cli 打印+非零退出、dashboard 走既有
  `_error` 分支——两处均**不执行** resume,满足 AC1。
- "同因"定义:**最近两条** suspended 的 reason_code 相等(第一条=本次,第二条=上一次);
  仅一条(首次挂起后首次 resume)→ 无"上一次",直接放行(AC4)。
- reason_code 为 None 的旧挂起:不参与同因判定(无法比对,放行,避免误伤存量)。

## How

1. `statemachine.resume` 签名改 `resume(pool, ticket, actor, force=False)`;
   函数体内既有校验后,读事件流取 suspended 事件列表(时间升序),取 reason_code 序列。
2. `len>=2` 且 `codes[-1]==codes[-2]` 且 `codes[-1] is not None` 且 `not force`
   → 抛 IllegalTransition(消息含 reason_code 与"--force/确认"提示)。
3. force=True 走原逻辑,append_event 的 `resumed` 事件补 `forced=True` 留痕。
4. `cli.py` resume 子命令加 `--force` flag,透传 `resume(..., force=args.force)`。
5. `dashboard/app.py` `/resume` 表单加 `force` 复选;路由读 `request.form.get("force")`
   透传。模板 approvals.html 的恢复表单加确认勾选(可后跟,不阻塞主链路,故列 P1)。

## Checkpoints

- [ ] 同因(codes[-1]==codes[-2] 非 None)+ 未 force → resume 抛 IllegalTransition,状态不变
- [ ] 同因 + force=True → 正常 resume,resumed 事件 forced=True
- [ ] 异因(codes[-1]!=codes[-2])→ 无警告直接放行
- [ ] 仅一条 suspended(首次 resume)→ 放行
- [ ] 最近 reason_code 为 None(存量旧挂起)→ 放行,不误伤
- [ ] cli `orc resume <id>` 同因未 --force → 非零退出+提示;`--force` → resumed
- [ ] 现有 resume 正常路径(非挂起/无 resume_state 仍 IllegalTransition)零回归
- [ ] `pytest tests/` 全绿(含新增同因用例)

## Rollback

新增 force 参数(默认 False)+ 一处同因检测,无 schema/数据迁移(事件流只读)。
回滚 = revert 本单提交,resume 恢复无检测现状。被误拦的 resume:revert 后重试即可,
或以 force 语义等价的人工确认绕过。
