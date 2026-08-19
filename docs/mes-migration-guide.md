# Odoo MES 回灌指南(后续独立立项,首轮不执行)

> 目标:odoo18-e-manufacture 从"决策树+记忆纪律"迁移到 ai-factory L2。原则:**并存渐进,不搞大爆炸替换**。

## 一、决策树章节 → 技能映射

| 99-decision-tree.md 章节 | 去向 |
|---|---|
| 一、主决策树概览 | CLAUDE.md 路由(薄) |
| 二、会话启动层 | session-start hook + backlog-keeper |
| 三、任务接收层 | phase0-proposal |
| 四、需求资料收集层 | phase1-requirements |
| 五/六、Phase 1/2 | phase1-requirements / phase2-design |
| 七、Phase 3 TDD | phase3-implement |
| 八/附录 E、Phase 3.5/5 | phase5-release + jenkins MCP(ci.trigger_ref) |
| 九、完成收尾层 | backlog-sync |
| 附录 B、门禁清单 | templates/gate-checklists/(按 MES 产物定制副本) |
| 附录 D、单人执行保障 | backlog-sync + mistake-retro |

## 二、记忆 → E 等级映射(首批 20 条)

| 现有记忆 | 建议等级 | 机制化载体 |
|---|---|---|
| 推送前跑 pyflakes | E3 | pre-push-lint(lint_cmd=pyflakes) |
| git commit+push 习惯 | E1(保留) | backlog-sync 步骤 |
| Odoo 18 不用 attrs | E2 | 脚本:grep -r 'attrs=' fj_custom/*/views/ |
| create 必加 model_create_multi | E2 | 脚本:检测 @api.model create 缺装饰器 |
| 新模型必须同步 ACL | E2 | 脚本:新 models 行 vs ir.model.access.csv |
| --test-tags 正确写法 | E1 | phase4-verify 指令 |
| env.get 返回空 recordset | E1 | memory 保留(判断类) |
| OWL 模板无全局函数 | E2 | 脚本:grep encodeURIComponent 等于 .xml |
| OWL 禁 inline delete | E2 | 脚本:grep 'delete ' 于 OWL 模板 |
| 视图必填联动 readonly | E1 | phase2-design 检查项 |
| 继承视图 evergreen 锚点 | E1 | memory 保留(判断类) |
| stored compute 跨模块 depends | E1 | phase2-design 检查项 |
| 唯一性校验 create/write 重写 | E1 | phase2-design 检查项 |
| 接口日志 is_success 派生 | E2 | 脚本:grep is_success.*True 硬编码 |
| jenkins 空选择参数传空格 | E3 | jenkins MCP 内建(已有) |
| 服务器 python3.12 + --no-http | E1 | phase5-release 指令 |
| odoo-bin 必须带 conf | E1 | phase4-verify 指令 |
| BOM 导入清空工序拆分 | E1 | memory 保留(业务知识) |
| Edit 追加必读真实结尾 | E0 | 工具使用习惯(文档) |
| 并发会话共用仓库 | E3(结构) | worktree-per-proposal(L3 试点) |

## 三、状态机兼容
- state.json schema 已对齐(modules/phase/milestones/budget),直接可用
- backlog.md 保留现有格式,session-start hook 的 sed 提取兼容 `## In Progress` / `## Blocked`
- stack-profile 建议值:lint_cmd=`python -m pyflakes {changed_files}`,ci.type=jenkins,ci.trigger_ref=`mcp:jenkins`,branch_model=`feature→test`

## 四、迁移顺序(立项后)
1. L0:根目录放 stack-profile.yaml(不动任何现有文件)
2. 装插件启用 hooks(观察 1 周,收集误报)
3. 决策树章节逐章替换为技能引用,99-decision-tree.md 退役为历史文档
4. 20 条记忆按上表晋升 E2/E3
5. L3 试点:选低风险需求走 worktree-per-proposal
