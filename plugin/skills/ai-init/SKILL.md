---
name: ai-init
description: 初始化新项目的 AI Factory 骨架(CLAUDE.md / backlog / state / memory / stack-profile)。当用户说"初始化项目""套用 AI 架构""setup 新项目""接入 ai-factory"时使用。
---

# AI Init — 项目骨架初始化

## 流程

1. 确定初始化位置(先问位置,再收集信息):
   - 用 AskUserQuestion 询问:在当前目录初始化,还是新建项目子目录?
   - 新建子目录时一并确认目录名(slug,小写中划线,如 `tiktok-ecommerce-ai`),可从项目名派生默认值
   - 原则:**一个目录 = 一个项目**;多项目工作区(容器目录)本身不初始化
2. 询问并逐项确认(用 AskUserQuestion,多选合并提问):
   - 项目名称、一句话简述
   - 主语言(python / typescript / 其他)
   - lint 命令(须含 `{changed_files}` 占位符;没有则留空)
   - 测试命令
   - CI 类型(jenkins / github / none)与分支模型(feature→main / feature→test / trunk)
3. 执行初始化(`--dir` 指向第 1 步确定的项目根):
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/scripts/init-project.sh --dir "<项目根>" \
     --name "<名>" --type "<简述>" --language "<语言>" \
     --lint-cmd "<lint命令>" --test-cmd "<测试命令>"
   ```
4. 按第 2 步答案手工补全 stack-profile.yaml 的 `ci.type` 与 `vcs.branch_model`
5. 展示产物清单,请用户审阅 stack-profile.yaml
6. 告知采用级别与后续:
   - L1(phase skills)立即可用;hooks 随插件启用即 L2
   - 若初始化在新子目录:提醒后续会话直接在该子目录启动;容器根目录的 init 提示应忽略

## 规则

- 脚本内置 **E3 防覆盖**:目标目录已有 CLAUDE.md / backlog.md / stack-profile.yaml / .claude/state.json 任一 → 拒绝执行
- 脚本内置 **E3 项目隔离**:目标目录的子目录已含其他项目骨架(判定为多项目容器) → 拒绝执行;应新建/指定项目子目录,**不要 --force 强刷容器根**
- 脚本自动补写目标目录缺失的 `.claude/settings.json`(插件启用配置);已存在则不改动
- 已有 CLAUDE.md 的项目 → 不要加 --force 强刷;改为手工把 `templates/claude-md.template.md` 内容作为 "## AI Factory" 章节追加到现有 CLAUDE.md
- `--force` 仅用于用户明确确认要重建骨架的场景,执行前提醒用户先备份
- **不执行 git init**(是否纳入版本管理由用户决定)
