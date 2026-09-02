# 设计:runner 推进读 QA verdict(不只认退出码)

- 工单:`pool/tickets/T-2026-0902-015.yaml`
- 阶段:P2 设计
- 关联:R11;溯源 T-2026-0902-010

## Architecture

在**产物门禁层**(`orchestrator/daemon/gates.py`)的 P4 边(`p4_verifying→p5_ready`)
追加 verdict 校验,与现有"验收报告存在+必含章节"机器项同层、同 GateFailed 语义,
不新开判定体系。

```
runner.advance_once
  └─ _transition_gated(pool, t, "p5_ready", actor="qa", project_dir)
       └─ statemachine.transition
            └─ _enforce_gate(project_dir, t, "p5_ready")
                 └─ gates.check_gate(...)          # 现有:产物/章节/留痕机器项
                      └─ 【新增】verdict 检查(仅 P4 边)
                           ├─ 读 04_测试/验收报告.md → 取 "## 结论" 章节正文
                           ├─ parse_verdict(结论正文) → pass | fail | unknown
                           └─ fail/unknown → 追加 FAIL 行(→ GateFailed → 挂起)
```

复用链:`_enforce_gate` 已在 `manifest_for_edge(p4_verifying, p5_ready)` 命中 P4 边,
`check_gate` 已定位并读验收报告。verdict 检查作为 P4 边**追加机器项**挂在
`check_gate` 内(报告已通过存在性/章节校验之后),天然 fail-closed——报告缺失/无
"结论"章节时,现有产物门禁已先 FAIL,verdict 检查只在报告结构合规后执行。

组件:
- `gates.parse_verdict(text) -> str`:纯函数,输入"结论"章节正文,返回
  `"pass" | "fail" | "unknown"`。判定优先级:**fail 优先**(命中"不通过"即 fail,
  防正文同时含"通过"字样误放,R6);其次 pass 族;都不中 → unknown。
- `gates` 在 check_gate 的 P4 分支调用 parse_verdict,`fail`/`unknown` 均追加 FAIL 行。
- runner 零改动:GateFailed 现有路径(挂起 + gate_failed 事件 + reason_code=
  verify_failed)自动接管——这正是 010 当初该有的收口。

判定词表(基于现有验收报告真实措辞采样):
- fail:`不通过`、`NO-GO`、`no-go`(优先级最高,任一命中即 fail)
- pass:`通过`、`验收通过`、`GO`、`放行`(须**不**同时命中 fail 词)
- 结论章节为空/两族都不命中 → unknown

## How

1. `gates.py` 新增 `parse_verdict(text)`,先按行扫描,命中 fail 词表即返 fail;
   否则命中 pass 词表返 pass;否则 unknown。fail 优先于 pass。
2. `check_gate` 在 P4 边(`stage == "P4"`):报告过存在性+章节校验后,
   用正则取 `## 结论` 至下一 `## `(或文末)正文,喂 parse_verdict;
   结果非 pass → 追加 `_fail(rel, f"QA 结论非通过(verdict={v}): 挂起退回")`。
3. verdict 判定写事件:runner 现有 GateFailed 分支已写 gate_failed(fails 含
   verdict 行),pass 路径在 state_changed 事件补充 `verdict=pass`(transition **ev)。
4. 其他推进边不受影响(verdict 检查仅挂 P4 边)。

## Checkpoints

- [ ] parse_verdict:"不通过,P4 挂起"→fail;"验收通过"→pass;"通过(8/8…)"→pass;
      "建议放行进入发布"→pass;空/无判定词→unknown;含"不通过"且含"通过"→fail(fail 优先)
- [ ] P4 边:报告结论 fail → transition 抛 GateFailed,fails 含 verdict 行,不推进
- [ ] P4 边:报告结论 unknown(缺判定词)→ 同样 GateFailed(fail-closed)
- [ ] P4 边:报告结论 pass + 产物门禁过 → 正常推进 p5_ready,事件留 verdict=pass
- [ ] 报告缺"结论"章节 → 现有产物门禁先 FAIL(不进入 verdict 分支)
- [ ] 非 P4 边(如 p3→p4、p5→monitoring)→ verdict 检查不触发,零影响
- [ ] `pytest tests/` 全绿(含新增 verdict 用例);conftest 门禁旁路不破坏

## Rollback

纯新增判定函数 + P4 边一处追加检查,无 schema/数据迁移。回滚 = revert 本单提交,
check_gate 恢复只做产物存在性/章节校验(现状)。被本闸误挂的在途工单:revert 后
resume 即恢复(或人工确认报告结论真实为通过后再推进)。
