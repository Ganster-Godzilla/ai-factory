# T-2026-0901-004 提案:release 契约补"部署"环节(本地/远程双形态)

## 问题(boss 实锤,2026-09-01)

release 契约只到"合 main + tag + 本地收口":push GitHub 靠手工兜底,部署到运行环境
**从来没有环节**。003/004 发布一夜,服务器 47.109.84.154 上 /api/store-profiles、
/api/login 仍 404——发布≠上线,boss 抓出。

## 核心约束(boss 2026-09-01 明确)

**没有云服务器时,CI/CD 就是本地化**——deploy target 必须抽象:
local 是一等公民(不是 remote 的降级),remote 是其中一种 target。

## 设计草案

### 1. 项目登记带 deploy 配置(orchestrator.yaml)

```yaml
projects:
  sk-video-studio:
    path: d:/workspace/sk-video-studio
    deploy:
      target: remote          # local | remote
      remote:
        host: 47.109.84.154
        user: deploy
        key: ~/.ssh/sk-aliyun-47
        app_dir: /data/apps/sk-video-studio
        service: sk-api       # systemctl 服务名
        build: ["cd apps/web && npm run build"]   # 部署前构建(本地侧)
      health:                 # 部署后冒烟(全 200 才算成)
        - /api/health
        - /api/store-profiles
        - /api/login
  ai-factory:
    path: d:/workspace/ai-factory
    deploy:
      target: local
      local:
        restart: [dashboard]  # 长驻进程重启清单(教训#1:合并后必须重启)
```

### 2. release 角色契约扩条款(roles/prompts/release.md + runner)

merge+tag 后:项目有 deploy 配置 → 执行 scripts/deploy.py → 健康检查冒烟:
- target=local:重启登记的本地长驻进程(dashboard 等,治教训#1 的根),冒烟本地端口
- target=remote:本地构建 → tar over ssh → 解包(留存上一版包)→ systemctl restart → 冒烟 health 清单
- 冒烟失败:建 incident 工单 + 回滚说明(上一版包回切),**不静默放行**

### 3. 回滚

- remote:/data/apps/releases/<时间戳> 逐版留存,app_dir 软链回切上一版 + restart
- local:git tag 回切 + 进程重启

### 4. 待 boss 决策

- **deploy 凭证保管**:SSH key 已有(~/.ssh/sk-aliyun-47);sudo 密码怎么管
  (deploy 用户 NOPASSWD 限定命令 / boss 每次现场输入 / 凭据文件 600 权限)
- ai-factory 自身的 local deploy 重启清单具体内容(dashboard 之外还有谁)

## 验收

1. 任一 feature 工单走 release 时,deploy 按契约自动执行(不依赖人记得)
2. local target(以 ai-factory 自身为试点)与 remote target(sk-video-studio)各演示一次
3. 冒烟失败路径演示一次:incident 自动建 + 回滚说明可用
4. pytest 全绿 + check-pool-load 0 bad

## 非目标

- 不做通用 CI/CD 平台(GitHub Actions/Jenkins 不引入)
- 不做多环境(dev/staging/prod 分级),单环境先行
- 不动现有 release 的合并/tag 语义
