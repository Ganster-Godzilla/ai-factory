# PRD-T-2026-0830-001: 需求产物布局统一(文件夹化)

> Phase 1 产物,源自 T-2026-0830-001(boss 2026-08-30 批准提案)。

## Why

需求产物两套布局并存:ARTIFACT_MANIFEST 写死扁平 `document/business/<id>-prd.md`,
技能流用 `<模块>/01_需求分析/`。扁平混排不可扫读(boss 实证 sk 仓 7 文件混排),
与"口径统一"相悖。

## What

**做**(2026-08-30 boss 指示扩大:全阶段产物进文件夹):
1. 统一布局:`document/business/<工单号>-<需求短名>/` 下——
   `00_提案/提案.md`、`01_需求分析/{prd,功能清单,歧义澄清记录}.md`、
   `02_设计文档/{design,tasks.yaml}`、`04_测试/验收报告.md`、
   `05_部署交付/{发布记录,观察窗报告}.md`。
   (03 开发无文件产物,验收留痕在工单 yaml task["verify"]。)
2. manifest 路径模板改工单文件夹相对式;gates 用 glob `<id>-*/` 前缀解析
   (短名纯人读,不参与机器判定;多匹配取字典序首个)。
3. 存量迁移:ai-factory(扁平 5 件 + 模块文件夹 3 个)与 sk-video-studio
   (扁平 7 件)git mv 进工单文件夹;ticket.artifacts/state.json 引用同步。
4. 技能模板 phase1-requirements、CLAUDE.md、使用指南口径同步。

**不做**:工单模型/状态机/门禁逻辑(仅路径解析);sk 两单内容;
T1-T12 无名遗留(原地保留登记);docs/superpowers/ 历史目录(不动)。
原"docs/specs 不动"边界经 boss 2026-08-30 指示作废,docs/specs 扁平产物同步迁移。

## 非功能需求

- 迁移用 git mv 保历史;迁移后全量 pytest 绿、check-pool-load 过、闸门自检(006/001 单)过。
- 文件夹解析零匹配=产物不存在(正常 FAIL);多匹配取字典序首个(确定性)。

## 验收标准

1. manifest 全部业务产物路径为新布局;docs/specs 路径不变。
2. 闸门对新布局工单(本单/006)正确放行与拦截(缺件 FAIL 含新路径)。
3. 两仓迁移完成,旧扁平路径零残留(git log 可溯)。
4. 全量 pytest 绿 + pyflakes 净 + check-pool-load 过。
