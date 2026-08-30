# 设计-T-2026-0830-001: 产物布局统一(工单文件夹化)

> Phase 2 产物。PRD:document/business/T-2026-0830-001-产物布局统一/01_需求分析/prd.md

## Architecture

```
artifacts.py   ARTIFACT_MANIFEST 全部路径模板 → document/business/{tid_dir}/阶段/文件
               + resolve_artifact_path()(统一解析器,{tid_dir} glob 前缀)
gates.py       check_gate 走统一解析器
runner.py      tasks.yaml lazy-load 走统一解析器(02_设计文档/tasks.yaml)
两仓迁移       git mv document/business 扁平件 + docs/specs 扁平件 → 工单文件夹
```

## How

- `{tid_dir}` 解析:document/business/<id>-*/ 前缀 glob,多匹配取字典序首个,
  零匹配 None(按产物不存在);短名纯人读不参与机器判定。
- 阶段目录:00_提案 / 01_需求分析 / 02_设计文档 / 04_测试 / 05_部署交付
  (03 开发无文件产物,verify 留痕在工单 yaml)。
- 迁移 ai-factory 9 工单文件夹 + sk 4 个;sk T-2026-0829-005 在跑不迁(闭环后补);
  ai-factory docs/specs 下 005 残留件属 SK 工单工作件,另行处置(不删他人产物)。

## 数据设计

无持久化变更;仅路径解析与文件位置。ticket.artifacts/state.json 引用同步改。

## 接口契约

| 面 | 变更 |
|---|---|
| resolve_artifact_path(project_dir, template, tid) -> str|None | 新增,共用 |
| ARTIFACT_MANIFEST 路径模板 | 全部 {tid_dir} 化 |
| 其余(状态机/事件/台账) | 不变 |

## Checkpoints

1. 既有 manifest/gates 用例改新路径全绿 + 新增 glob 用例
2. 本单自身 P2/P4/P5 门禁按新路径放行(dogfood)
3. 全量 pytest 绿 + pyflakes 净 + check-pool-load 过

## Rollback

纯路径与文件位置变更;代码 revert + git mv 反向即回。门禁逻辑本身零改动。

## 测试用例设计映射

| 功能清单 | 测试 |
|---|---|
| F1 路径模板 | test_artifacts_manifest 全部路径断言 |
| F2 glob 解析 | test_biz_dir_glob_resolution(多匹配取首/零匹配 None) |
| F3 迁移 | 人工核验(git log)+ 验收标准 3 |
| F6 runner 装载 | test_p3_lazy_loads_tasks_yaml(新路径命中) |
| F5 测试 | 本文件覆盖 |
