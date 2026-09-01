---
name: phase5-release
description: Phase 5 部署发布。合并分支、打 tag、部署、目标环境冒烟验证、发布记录留痕、交付收尾时使用。
---

# Phase 5 — 部署发布

## 契约条款(T-2026-0901-004:release 契约补"部署"环节)

发布≠上线:release 必须走完 **合并 → tag → deploy 脚本 → 冒烟 → 记录** 五步,
部署执行在脚本里,不靠人记得(003/004 发布一夜未上服务器即教训)。

1. **合并**:按 stack-profile `vcs.branch_model` 合并(不询问,直接按模型执行)
2. **tag**:合并后打版本 tag(git describe 供部署脚本取版本)
3. **deploy 脚本**:执行 `python -m orchestrator.daemon.deploy <工单号> [--allow-deps-change]`
   - 项目登记了 orchestrator.yaml `deploy:` 配置 → 自动执行部署流水线
     (remote:本地构建 dist→tar+ssh 上传→解包留版 chown 归一→依赖/.env 前置检查→
     current 回切→restart_cmd 重启;local:按 processes 清单重启长驻进程)
   - 未登记 → 发布记录"部署清单"章节写显式声明"未登记 deploy,本单纯代码交付",章节仍在
   - 脚本非零退出 = 冒烟/部署失败,已自动建 incident 工单+回滚说明,判负走既有挂起链路
4. **冒烟验证**:deploy 脚本内置冒烟(smoke URL 逐个 GET 期望 200,失败重试 3 次);
   结果全量留痕写发布记录"冒烟结果"章节,任一非 200 即整体失败
5. **记录**:发布记录必含章节(门禁机器校验,口径与 ARTIFACT_MANIFEST 一致)
   合并清单 / 版本 / 部署清单 / 冒烟结果 / 回滚方案

## 规则
- 回滚方案必须可照抄执行:remote=`ln -sfn releases/<上一版> current && <restart_cmd>`;
  local=`git checkout <上一 tag>` + 进程重启
- 依赖差异必须前置声明:服务器不现场装新依赖;需变更时发布单显式声明处置方式
  (发布记录必写 venv 重建说明),或 `--allow-deps-change` 放行
- .env 密钥不落库:只比 key 名,差异清单进部署单,值永不回传/入记录
- 冒烟失败不静默放行:自动建 incident 工单 + 回滚说明随附,退出码非零

## 门禁
gate-check(phase5)
