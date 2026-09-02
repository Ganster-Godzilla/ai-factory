# T-2026-0902-006 设计:loop 合 main 走受保护路径

## Architecture

```
dev-loop "切片即合 main"(规则#11 快道)
  │  新增前置:orc guard pre-merge <project_dir>
  │    ├─ git fetch origin
  │    ├─ git log origin/main..HEAD:
  │    │     空 → 过
  │    │     非空且全部命中 loop 签名白名单 → 过
  │    │     否则 → 非零退出 + 打印他人提交清单(拦截)
  │    └─ git status --porcelain 非空(非本切片) → 拦截
  ├─ 过 → 照旧 merge;合并结果写事件流 loop_merge{ticket, base, head_before, head_after}
  └─ 拦 → 工单挂起 + 报警(他人工作在飞,人工对齐后再合)
```

- **gitguard.py**(纯增量新模块):`check_pre_merge(project_dir, *, allowed_prefixes)
  -> list[Blocker]`;白名单默认 ("merge(orc/", "merge(S", "chore(S",
  "merge(T-", "fix(T-", "feat(T-", "docs(T-", "release(T-") —— 工单号前缀与
  loop 模式;不认识的一律视为他人(宁可误拦);
- **CLI**:`orc guard pre-merge <project_dir>`(cli.py 加子命令,退出码 0/2);
- **playbook 接线**:docs/orchestrator-guide.md 规则#11 相关段 + 驱动会话提示词
  ("切片即合 main" 改为 "先 orc guard pre-merge,绿才合");
- **审计**:合并成功处 append_event(loop_merge)(在调用守卫的合并点由 dev-loop
  报告;守卫模块提供 make_loop_merge_fields() 助手)。

## How

- S1:gitguard.py + CLI + pytest(tests/orchestrator/test_gitguard.py:
  临时仓构造四种场景)+ guide/提示词接线文本 + 本单验收
  `python -m pytest tests/orchestrator/test_gitguard.py -q` 全绿 +
  `orc guard pre-merge` 在 ai-factory 仓实测(当前干净应通过);
- 验收脚本入口即 acceptance_cmd。

## Checkpoints

1. pytest test_gitguard.py 全绿;
2. `orc guard pre-merge d:/workspace/ai-factory` 实仓通过(当前无他人提交);
3. guide 文本 grep 到守卫指令。

## Rollback

守卫为纯增量(新模块+新 CLI 动词+提示词文本),revert 即回滚;
最坏情况(loop 忘跑守卫)= 回到现状,无新增故障面。
