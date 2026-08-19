# AI Factory 分发与安装指南

> 面向:把 ai-factory 插件装到其他机器、给其他同事使用。

## 前置要求(目标机器)

| 依赖 | 说明 | 检查命令 |
|---|---|---|
| Claude Code | 支持 plugins 的版本(IDE 扩展或 CLI 均可) | `claude --version` |
| Bash | Windows 用 Git Bash;macOS/Linux 自带 | `bash --version` |
| python | 必须在 PATH(hook 内 JSON/YAML 解析用),3.8+ | `python --version` |

⚠️ Windows 特有:所有脚本已强制 UTF-8 + LF 输出,**不要**用编辑器把 `.sh` 存成 CRLF。

## 通道一:目录拷贝(零基础设施,适合 1-3 台机器)

1. 把整个 `ai-factory/` 目录拷到目标机器任意位置(zip / 共享盘 / scp / 飞书文件均可),例如 `D:\tools\ai-factory`
   - 可排除:`docs/superpowers/`(设计过程文档)、`tests/fixtures` 以外无需精简,整个目录 < 200KB
2. 在目标机器注册本地 marketplace(一次性,用户级):
   ```bash
   claude plugin marketplace add D:\tools\ai-factory
   ```
3. 启用(二选一):
   - **项目级(推荐,A 方案)**:在要用它的项目里建 `.claude/settings.json`:
     ```json
     { "enabledPlugins": { "ai-factory@ai-factory-local": true } }
     ```
   - **全局**:在用户 `~/.claude/settings.json` 的 `enabledPlugins` 加同样一行——所有项目生效
4. 验证:
   ```bash
   bash D:\tools\ai-factory\tests\e2e.sh
   ```
   输出 `E2E PASS` 即安装成功;再按 `tests/e2e-manual-checklist.md` 过一遍 LLM 行为项。

## 通道二:git 仓库(团队长期推荐)

> 注:本目录本地不做 git 管理(决策记录见 spec);此通道是**单向发布**——发布时 push,不改变本地工作方式。

1. 把 `ai-factory/` push 到内部 git 服务(GitLab/Gitea/GitHub 内网均可),例如 `http://git.internal/team/ai-factory`
2. 他人安装:
   ```bash
   claude plugin marketplace add http://git.internal/team/ai-factory
   claude plugin install ai-factory@ai-factory-local   # 全局启用;项目级启用同通道一第 3 步
   ```
3. 升级:
   ```bash
   claude plugin marketplace update ai-factory-local
   ```

## 两种通道对比

| | 目录拷贝 | git 仓库 |
|---|---|---|
| 基础设施 | 无 | 内部 git 服务 |
| 升级传播 | 重新拷贝 + 重新 add | `marketplace update` 一键 |
| 版本轨迹 | 无(靠 docs 日期标注) | tag/commit |
| 适合 | 试用、1-3 台 | 团队正式分发 |

## 新项目首次使用

在任何项目目录里(已按上节启用插件):

```
/ai-factory:ai-init
```

交互式生成 CLAUDE.md / backlog.md / .claude/state.json / stack-profile.yaml。脚本带 E3 防覆盖:已有这些文件的项目会拒绝执行并提示合并方式。

## 卸载 / 临时禁用

- 项目级:删项目 `.claude/settings.json` 里的 `enabledPlugins` 行(或改 `false`)
- 全局:删用户 settings 同行;`claude plugin marketplace remove ai-factory-local` 取消注册
- 禁用后 hooks 立即停止,skills 不再出现;项目内已生成的 backlog/state 等文件不受影响

## 常见问题

- **hooks 不触发**:确认 `enabledPlugins` 的键是 `ai-factory@ai-factory-local`(marketplace 名@插件名不要写反);确认 marketplace 已 add
- **lint 拦截误伤**:stack-profile.yaml 的 `lint_cmd` 留空即关闭该 hook,其余 hook 不受影响
- **会话启动没有摘要**:项目根缺 backlog.md / .claude/state.json——先跑 `/ai-factory:ai-init`
- **python 相关报错**:确认 `python`(非仅 `python3`)在 PATH;Windows Store 占位 python 需装真包
