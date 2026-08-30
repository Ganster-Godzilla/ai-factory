# 设计-T-2026-0828-003: 编排器健壮性八缺口修复

> Phase 2 产物。PRD:document/business/T-2026-0828-003-prd.md
> 总原则:**状态推进必须有产物和账的双重证据;验收失败反馈必须含失败子句;成本台账必须覆盖 k3 与 DeepSeek 两侧。**

## 1. 现状诊断(缺口 → 根因定位)

| # | 缺口 | 根因(代码位置) |
|---|---|---|
| R1 | 产物验收缺口 | `runner.advance_once`:`result.status=="done"` 直接 `transition`,无产物校验(runner.py:242-247) |
| R2 | 无 P1 重做边 | `statemachine.TRANSITIONS["p1_proposed"]` 只有 `p2_designing`/`closed`(statemachine.py:13) |
| R3 | dsh 台账漏记 | `DshAdapter.run` 返回的 `HarnessResult` 不填 `tokens`/`cost_cny`(dsh.py:62),`_record_cost` 收到 0 即 `if amount` 跳过入账(runner.py:76) |
| R4 | 周计数虚高 | relay(`D:\Tool\kimi-relay.js`)的 `weekInputTokens` 把 cache_read 计入;`gateway.py:16` 原样求和 |
| R5 | 验收反馈失明 | 验收命令多为 `grep -q` 类静默命令,exit=1 时 stdout/stderr 无内容,`tail` 拿不到失败子句(runner.py:143-150) |
| R6 | 验收口径脆 | 架构师产出的 `acceptance_cmd` 用裸 grep 字面量/行数判定,无规范化 |
| R7 | scope 无强制 | tasks.yaml 无 scope 字段,runner 验收不查改动文件清单 |
| R8 | 超时一刀切 | `TaskPacket.timeout=1800` 唯一档(base.py:18),acceptance 固定 600s(runner.py:80) |

## 2. 设计决策

### D1(R1)产物验收闸门:EXPECTED_ARTIFACTS 契约

- runner 新增模块级契约(放 runner.py,不新建文件):

```text
EXPECTED_ARTIFACTS = {
    "p1_drafting":  ["document/business/{tid}-prd.md"],
    "p2_designing": ["docs/specs/{tid}-design.md", "docs/specs/{tid}-tasks.yaml"],
}
```

- `advance_once` 中 `result.status=="done"` 后、`transition` 前:按当前态查契约,`{tid}` 替换工单号,在 `project_dir` 下逐一校验「存在且 size>0」。
- 缺产物 → **不推进**:记事件 `artifact_missing`(含缺失文件清单),按 role 执行失败路径挂起,`reason_code="artifact_missing"`(加入 `SUSPEND_REASON_CODES`)。
- 无契约的态(p3/p4/p5/monitoring)不校验,行为不变。
- `p2_designing` 分支现有「置 owner_role=boss 不迁移」逻辑,闸门同样先于它生效。
- 双重证据闭环:账的证据由既有 `_record_cost`(成功失败都入账)保证;本闸门补产物证据。事件 `role_run` 增加字段 `artifacts_checked: [path,...]`,便于审计「推进时校验过哪些产物」。

### D2(R2)P1 重做路径

- `TRANSITIONS["p1_proposed"]` 增加 `"p1_drafting": {"boss"}`(驳回=回到 PM 重做,actor 限定 boss)。
- CLI:`orc reject <id>` 默认仍 → closed;新增 `orc reject <id> --redo` → `p1_drafting`(仅当当前态为 `p1_proposed`,否则 IllegalTransition)。审批中心 UI 不动(PRD 范围外)。
- 轮次追踪:Ticket 增字段 `p1_round: int = 0`,每次 redo 迁移时 +1 并随 `state_changed` 事件记录 `round=N`;不重置,历史轮次经事件流可追。PM 重做 prompt 由 runner 拼接时附「第 N 轮重做」上下文(利用既有 `_role_prompt` 拼接点,不新增机制)。
- 兼容:既有工单 yaml 无 `p1_round` 字段,`load_ticket` getattr 兜底为 0,平滑迁移。

### D3(R3)dsh 成本+token 台账

- **dsh 侧硬契约**:dsh headless 模式结束时在 stdout 末行输出 usage trailer:
  `__DSH_USAGE__ {"input_tokens":N, "output_tokens":N, "cost_cny":X.XX}`
  (dsh 为自有工具,trailer 由 dsh 仓库实现;本工单在 adapter 侧定义契约并消费。)
- `DshAdapter.run`:解析并剥离 trailer,填入 `HarnessResult.tokens={"input_tokens","output_tokens"}` 与 `cost_cny`;剥离后的正文作为 `output`。
- 解析不到 trailer(旧版 dsh)→ 返回 `status="failed"`,`output` 注明「dsh 未输出 usage trailer,台账无证据,视同失败」——**无账不推进**,与总原则一致;同时记事件 `usage_missing`。
- `ledger.append_ledger` entry 扩展两字段:`tokens: {input, output}`、`calls: 1`;k3 侧 `_record_cost` 同步写入同一结构(口径对齐,三字段齐全)。旧 entry 缺字段时查询端 `.get` 兜底。
- 新增查询 `ds_day_calls(pool)`(次数=当日 deepseek entry 数);`ds_day_cost`/`ds_ticket_cost` 不变——记录补上后 ¥30 日线与 ¥10 工单帽自然生效,闸门逻辑零改动。

### D4(R4)relay 周计数口径修正

- 改动面在 `D:\Tool\kimi-relay.js`(独立 git 仓,本工单唯一跨仓任务):周累计口径改为「非缓存输入 + 输出」,即从 `weekInputTokens` 中剔除 cache_read/cache_creation;`/​__stats` 新增独立展示字段 `weekCacheReadTokens`(只展示,不进预算)。
- 口径目标:与 Kimi 控制台周用量偏差 ≤10%。
- 编排器侧 `gateway.py` 零改动(已只求和 input+output,relay 口径一正即对齐)。
- 回归:`orchestrator.yaml` 的 30M 临时提额注释更新;**回落目标值是 PRD 开放问题 3**,本设计建议口径修正上线并观察一个完整自然周后由老板决定(建议回 3M)。回落本身是改一个数字的手工操作,不占任务切片;G4 验收只要求「含大量 cache_read 的构造流量不使周计数显著膨胀」。
- 测试:relay 仓新增 `test/relay-stats.test.js`,用含 cache_read 的 usage fixture 断言周计数口径。

### D5(R5)验收失败子句回传

- **约定优先**:验收命令/脚本失败时必须向 stdout 打印 `FAIL: <失败子句>` 行(一行一条);doccheck(D6)与 scope 检查(D7)均遵守此约定。裸 shell 命令无 FAIL 行时,证据仍由 tail 兜底。
- runner 验收失败反馈格式定型(写入 `result.output` 与 `task["last_error"]`,头部即证据):

```text
[acceptance 复检失败 exit=N] 命令: <acceptance_cmd>
FAIL: <子句1>            ← 提取的所有 FAIL: 行,置顶,无则省略本段
--- 输出尾部 ---
<stdout+stderr 尾部 2000 字符>
--- harness 输出(截断) ---
<原 output[:500]>
```

- `task["last_error"]` 截断长度 800 → 2000,保证 FAIL 行与尾部证据不被 `retry_prompt` 的 `[:800]` 切掉(`retry_prompt` 同步放宽到 2000)。
- 验收命令本体写入反馈:dev 重试时能看到「是哪条命令、哪条子句失败」,不再盲猜。

### D6(R6)验收命令口径健壮化:doccheck

- 新增 `orchestrator/daemon/doccheck.py`,CLI:`python -m orchestrator.daemon.doccheck <md文件> --require-section "Why" --require-section "验收标准" [--forbid "TODO"]`。
- 规范化后再匹配:统一 CRLF/LF、压缩连续空白行、标题层级不敏感(`## X` 与 `### X` 均命中 `--require-section X`)、行内多余空格忽略。
- 失败时打印 `FAIL: 缺少章节 "X"` / `FAIL: 命中禁用词 "TODO"`(遵守 D5 约定),exit=1;全过 exit=0。
- `roles/prompts/architect.md` 增补约定:**文档类产物的 acceptance_cmd 一律用 doccheck,禁止裸 grep 字面量/行数判定**;代码类产物仍用 pytest 等行为判定。
- 本工单自身 tasks.yaml 即按此约定书写(吃狗粮)。

### D7(R7)scope 越界强制检查

- tasks.yaml 任务新增可选字段 `scope: [glob, ...]`(相对项目根,fnmatch 语义,`**` 递归)。缺省不检查(兼容旧清单);`roles/prompts/architect.md` 约定:**改代码的任务必须写 scope**,全开工写 `["**/*"]` 以示显式。
- 检查时机:dev 返回 done 之后、验收命令之前(越界属致命,不必再烧验收)。
- 改动文件清单来源:worktree 内 `git status --porcelain`(未跟踪+已修改)+ `git diff --name-only <base>`(已提交);`base` 由 `worktree.ensure_worktree` 在创建 worktree 时把当前 HEAD 写入 `worktree/.orc-base` 落盘,检查时读取。两个命令已存在则沿用,无 base 文件时退化为仅 `git status --porcelain`。
- 越界 → 视同验收失败:`verify="failed"`,反馈头部打印 `FAIL: scope 越界: <文件清单>`(遵守 D5 约定),走既有重试阶梯,dev 下一轮能直接看到越界文件列表。
- worktree.py 只新增「写 base 文件」一个动作,不改动创建逻辑。

### D8(R8)超时分级

- tasks.yaml 任务新增可选字段 `timeout: <秒>`,缺省 1800;装载时校验上限 `MAX_TASK_TIMEOUT = 7200`(slicer 常量),超限 `load_task_list` 直接报错(防止切片侧无限放大)。
- 档位约定(写进 architect.md):normal=1800(缺省)/ env(依赖安装、环境准备)=3600 / 上限 7200。取 3600 而非 5400:B1 实测 pip 25 分钟=1500s,3600 有 2.4x 余量且仍远小于无界。
- `slicer.make_packet` 把 `task.get("timeout", 1800)` 传入 `TaskPacket.timeout`;`TaskPacket` 默认值保持 1800 不变(非切片路径行为不变)。
- 验收命令超时:`_run_acceptance` 的 600 固定值改为 `task.get("acceptance_timeout", 600)`,同样受 7200 上限校验;acceptance_timeout 独立于 task timeout(env 任务的安装发生在 dev 侧,验收通常很快,分开配置)。
- orchestrator.yaml 不新增配置项:档位是切片属性不是全局属性。

## 3. 对既有契约的兼容

- 状态机只加边不删边;`APPROVALS` 不变;进行中工单无需迁移。
- ledger.jsonl append-only,新字段向后兼容(查询端 `.get` 兜底)。
- tasks.yaml 新字段全部可选,旧清单装载行为不变(`load_task_list` setdefault 模式沿用)。
- relay 改动在独立仓,失败不影响编排器其他功能(网关不可达既有 fallback 逻辑不变)。

## 4. 开放问题的设计裁决(PRD §歧义)

1. R6 容忍边界 → D6 规范化清单即边界:换行/连续空白/标题层级/行内空格=合理变体;缺章节、命中禁用词=内容缺失。正反例写进 doccheck 测试 fixture。
2. R8 档位 → D8:env=3600,上限 7200;后续有新类型再加约定,不提前抽象。
3. R4 提额回归目标 → D4:不在本工单代码内决定,观察一周后老板拍板(建议 3M),设计留痕。
4. AC-2 驳回入口 → D2:CLI `orc reject --redo`;PRD 明确不做 UI,审批中心按钮留给后续工单。

## 5. 风险

- **G4 跨仓**:relay 在 `D:\Tool`,runner 的 worktree 机制不适用。dev 直接在 `D:\Tool` 工作,验收命令 `cd /d/Tool` 开头;该任务 scope 字段无意义,写 `["**/*"]` 并在 prompt 注明例外。
- **dsh trailer 依赖 dsh 仓配合**:若 dsh 侧未同步上线 trailer,G3 的「无 trailer 即 failed」会阻断所有 dsh 角色。缓解:G3 验收含「旧 dsh(无 trailer)→ failed + usage_missing 事件」用例,上线顺序 = 先确认 dsh 已支持 trailer 再合入;若不可控,把「无 trailer 即 failed」降级为「failed 但可经 config 开关放行」不做——坚持无账不推进。
- **D1 产物路径硬编码**:PRD 路径约定(`document/business/`)来自本单 PRD 实例;若 PM prompt 约定变化需同步 EXPECTED_ARTIFACTS。已在 pm.md 路径约定处用同一字符串,测试覆盖。
