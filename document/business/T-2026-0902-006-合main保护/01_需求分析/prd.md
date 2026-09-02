# T-2026-0902-006 PRD:loop 合 main 走受保护路径

## Why

2026-09-01 实证:交互会话已在 main 提交的 SOP 文档被 loop 合 main 窗口挤掉
(未入任何历史;reflog/fsck 取证)。机制推断(从证据能站住的最远点):
loop 合 main 前会把 main 同步回 origin/main(重置类操作),**本地未推送的他人
提交被静默丢弃**。release 角色路径("唯一能合 main")是好的;漏洞在 dev-loop
的"切片即合 main"快道(规则#11 为集成连续性而设)无前置检查。sk 侧已立分支
纪律(T-2026-0902-005);loop 作为合 main 的机器本身必须有守卫。

## What

1. **合并守卫**(新):`orchestrator/daemon/gitguard.py` + CLI 动词
   `orc guard pre-merge <project_dir>`:
   - `git fetch` 后检查 `git log origin/main..HEAD`:非空 = 存在本地未推送提交;
   - 其中凡非本 loop 本次运行自建的提交(commit message 前缀不在 loop 签名
     白名单:merge(orc/、merge(S、chore(S 等,可配置)→ **非零退出 + 打印
     他人提交清单**(hash/作者/时间/首行);
   - 工作区/索引有非本切片脏文件同样拒绝;
2. **接线**:dev-loop playbook"切片即合 main"步骤改为**先跑守卫再合**
   (提示词/指南文本,规则#11 处);release 角色路径不变(已受 boss P5 审批保护);
3. **合并审计**:loop 每次合 main 写事件流(loop_merge 事件:工单/基线 hash/
   合并前后 HEAD),事故可追溯;
4. 守卫自身 pytest(orchestrator 测试目录):干净通过/他人提交拦截/脏树拦截/
   白名单放行。

## 验收标准

1. 构造:main 上有"他人"未推送提交 → 守卫非零退出且清单指名;
   仅 loop 签名提交 → 通过;脏树 → 拒绝;
2. dev-loop 指南/提示词文本含"合 main 前先跑 orc guard pre-merge"(grep 级断言);
3. orchestrator pytest 全绿(新增用例+零回归);
4. 合 main 事件(loop_merge)在事件流可查。

## 不做

- 不动 release 角色的 P5 审批链;不引入 GitHub 分支保护(本地守卫先行);
- 不改 worktree 机制;不追昨夜事故责任(已修复,重在防再犯)。
