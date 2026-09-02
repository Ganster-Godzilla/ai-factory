# 设计:复杂度闸接入常设质量闸

- 工单:`pool/tickets/T-2026-0903-003.yaml`
- 阶段:P2 设计

## Architecture

新增 `scripts/check-complexity.py`(与 check-pool-load 同级、sys.path.insert 直跑),
radon 提供精确 cc 数值;基线清单冻结存量,只拦增量/恶化。

```
scripts/check-complexity.py
  ├─ 调 radon(cc 数值):radon cc orchestrator/ plugin/ scripts/ --json(或 cc -s 解析)
  ├─ 收集 { (rel_path, qualname): cc } 全量函数
  ├─ 读基线 scripts/complexity-baseline.txt → { (rel_path, qualname): baseline_cc }
  ├─ 判定(阈值 THRESHOLD=15):
  │    对每个 cc>15 的函数:
  │      不在基线 → 命中【新增超标】
  │      在基线 且 cc > baseline_cc → 命中【恶化】
  │      在基线 且 cc ≤ baseline_cc → 豁免
  ├─ 命中非空 → 打印清单 + return 1;否则 return 0
  └─ radon 缺失(ImportError/无此命令)→ 打印"pip install radon"+ return 2(不静默放行)
```

基线格式(`scripts/complexity-baseline.txt`,一行一个,`::` 分隔,易 diff):

```
orchestrator/daemon/cli.py::main::25
orchestrator/daemon/gates.py::check_gate::24
orchestrator/adapters/dsh.py::DshAdapter.run::23
orchestrator/daemon/deploy.py::load_deploy_config::21
...
```

radon 输出解析:`radon cc <dirs> --json` 给 per-file 块,每块 entries 含
name/classname/lineno/complexity;qualname 拼 `classname.name`(函数)或 `name`。
**注意 002 已拆 run_dev_tasks(46→4),基线不含它**;基线在 S1 首次生成时按现状取。

## How

1. requirements.txt 加 `radon`。
2. 写 `scripts/check-complexity.py`:radon json 解析 + 基线比对 + 闸语义 + 无 radon 报错。
3. 生成基线:跑脚本 `--write-baseline` 模式(或手动)按现状 cc>15 函数写入
   complexity-baseline.txt(排除已拆的 run_dev_tasks)。
4. TDD:tests 加用例——构造含 cc>15 函数的临时 py 文件,断言被拦;基线内函数
   豁免;基线函数 cc 升高被拦;无 radon 报错路径。
5. CLAUDE.md "纪律要点"补一句:合 main 前 `python scripts/check-complexity.py`。
6. 验证 AC1-AC6。

## Checkpoints

- [ ] AC1 当前仓跑返回 0(基线豁免)
- [ ] AC2 新增 cc>15 函数 → 非零+点名
- [ ] AC3 基线函数 cc 调高 → 非零;调低 → 放行
- [ ] AC5 屏蔽 radon → 非零+提示(非静默)
- [ ] radon json 解析正确(qualname 拼法对齐 radon 实际输出)
- [ ] pytest tests/ 全绿(含新闸自测)
- [ ] CLAUDE.md 补使用说明

## Rollback

纯新增脚本+基线文件+一行 requirements,无 schema/数据迁移。回滚 = revert 提交,
合 main 守卫恢复只跑 check-pool-load。风险:radon json 结构与版本相关——
用 `--json` 稳定字段(name/complexity/classname),解析失败按"无 radon"响亮报错,
不静默放行。
