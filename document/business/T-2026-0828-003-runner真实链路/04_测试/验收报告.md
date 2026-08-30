# 验收报告 — T-2026-0828-003(黑盒执行)

> 执行角色:QA(测试执行)。依据:`docs/specs/T-2026-0828-003-tasks.yaml` 逐条执行 `acceptance_cmd`。
> 执行时间:2026-08-28。环境:Windows / Python 3.11.5 / pytest 9.1.1 / node v24.14.0 / git-bash D:\Git(cygwin)。

## 0. 执行环境声明(影响判读)

1. **PYTHONPATH 准备**:脚本式 `pytest` 在本机不注入仓库根到 `sys.path`(tests/ 无 `__init__.py`),字面命令收集即报 `ModuleNotFoundError: No module named 'orchestrator'`。执行时以 `PYTHONPATH=<仓库根>` 准备环境后按字面命令运行(与编排器 runner 的运行方式一致)。
2. **git-bash 沙箱限制**:本执行会话的文件沙箱阻止 cygwin 共享内存段创建,git-bash 启动即崩溃(`*** fatal error - CreateFileMapping S-1-5-21-… Win32 error 5`),`bash -c "exit 0"` 返回 rc=256。因此**所有「验收命令经 bash 真实执行且需通过」的用例被误判为 failed**。沙箱权限升级审批通道不可用(escalation rejected, fail-closed)。受影响用例:`test_runner.py::test_none_budget_survives_cap_gate`(唯一依赖验收命令成功执行的用例),在 G2/G3/G5/G7/G8 中各计 1 failed。
3. **node 子进程限制**:`node --test` 以管道捕获方式派生子进程,被沙箱拒绝(`spawn EPERM`,文档化边界)。G4 按免管道等价方式重组执行:`node test/relay-stats.test.js`(同文件、同断言、单进程运行)。

## 1. 逐条结果

| 任务 | 验收命令(字面) | 判定 | 明细 |
|---|---|---|---|
| G1 | `pytest tests/orchestrator/test_statemachine.py tests/orchestrator/test_cli.py -q` | ✅ PASS | 9 passed in 2.39s |
| G2 | `pytest tests/orchestrator/test_runner.py -q` | ⚠️ FAIL(环境性) | 17 passed / 1 failed:`test_none_budget_survives_cap_gate` |
| G3 | `pytest tests/orchestrator/test_dsh_adapter.py tests/orchestrator/test_ledger.py tests/orchestrator/test_runner.py -q` | ⚠️ FAIL(环境性) | 30 passed / 1 failed(同一用例) |
| G4 | `cd /d/Tool && node --test test/relay-stats.test.js` | ✅ PASS(等价执行) | 3/3:isoWeek 格式 / 同周累计 / 跨周窗口清零;字面命令因沙箱 spawn EPERM 无法原样执行,见 §0.3 |
| G5 | `pytest tests/orchestrator/test_runner.py tests/orchestrator/test_circuitbreaker.py -q` | ⚠️ FAIL(环境性) | 20 passed / 1 failed(同一用例) |
| G6 | `pytest tests/orchestrator/test_doccheck.py -q` | ❌ FAIL(交付缺失) | `file or directory not found`,exit=1;实现遗留在 `.orc-worktrees/T-2026-0828-003-G6/` 未合并,该 worktree 内同命令 17 passed |
| G7 | `pytest tests/orchestrator/test_runner.py tests/orchestrator/test_worktree.py tests/orchestrator/test_slicer.py -q` | ⚠️ FAIL(环境性) | 23 passed / 1 failed(同一用例) |
| G8 | `pytest tests/orchestrator/test_slicer.py tests/orchestrator/test_runner.py -q` | ⚠️ FAIL(环境性) | 22 passed / 1 failed(同一用例) |

**Playwright 脚本**:本计划无 Playwright 用例(tasks.yaml 全部为 pytest/node;全仓检索仅设计文档提及 Playwright 分流原则),无脚本可执行。

## 2. 失败子句(按 D5 约定格式)

```text
FAIL: test_runner.py::test_none_budget_survives_cap_gate — assert 'retry:task-1:1' == 'task:task-1:done'
      根因=执行环境:git-bash(cygwin)在沙箱内无法启动(CreateFileMapping Win32 error 5),
      验收命令 `exit 0` 未被执行即返回非零 → verify=failed → retry。
      用例逻辑本身(工单帽闸 budget=None 容错)不涉及该路径,非产品缺陷证据。
FAIL: G6 — tests/orchestrator/test_doccheck.py 不存在于主仓(doccheck 模块未合并)
```

## 3. 字面 exit code 之外的质量观察

1. **G4 设计意图未达成(D4)**:`test/relay-stats.test.js` 无「大量 cache_read 的 usage fixture,断言周计数不膨胀」用例(仅 isoWeek/累计/跨周 3 例);`kimi-relay.js:86` 正则 `"(input|output)_tokens":(\d+)` 原样取 `input_tokens`,`relay-stats.js` 的 `recordUsage(st, inT, outT)` 无 cache 参数、无 `weekCacheReadTokens` 字段。**字面命令通过,但「周计数剔除 cache_read」口径未实现**。
2. **G4 上下文项未完成**:`orchestrator.yaml:12-15` 仍写「临时提至 30M 解闸…治本入改进清单」,未按 D4 更新为「口径已修,回归值待定」。
3. **G6 合并动作缺失**:`.orc-worktrees/T-2026-0828-003-G6/` 内 `orchestrator/daemon/doccheck.py` 与 `tests/orchestrator/test_doccheck.py` 存在且 17/17 通过,主仓缺失——需合并后重跑 G6。
4. **唯一产品疑点**:`test_none_budget_survives_cap_gate` 建议在 git-bash 可用环境复跑确认(本报告判其为环境性失败,证据见 §0.2)。

## 4. 复跑指引

- G2/G3/G5/G7/G8:在 git-bash 可正常启动的环境(无 cygwin 共享内存限制)原样重跑即可;预期 5 条全绿。
- G6:将 G6 worktree 的 doccheck 合并主仓后重跑。
- G4:沙箱外用字面命令 `cd /d/Tool && node --test test/relay-stats.test.js` 复核;并按观察 1 补 cache_read 用例后再判 D4 完成。
