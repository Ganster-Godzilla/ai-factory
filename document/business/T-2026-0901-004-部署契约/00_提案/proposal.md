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

## 实战情报(首次部署 2026-09-01,workspace-8d 一线回传,设计必须消化)

1. **sudo 卡点**:sk-api 以 root 跑、deploy 无免密 sudo → 契约二选一:
   sudoers 白名单(`systemctl restart sk-api` 单条 NOPASSWD,推荐)或服务改 User=deploy
2. **uid 穿透**:本机 tar 保留 uid=197609,服务器 deploy 不可写 → 发布脚本必须
   `chown -R deploy`(或 tar 加 --owner 部署时归一)
3. **venv 策略**:服务器 python3-venv/ensurepip 缺失,新 venv 建不了——本次靠
   "零新依赖设计"复用旧 venv 得救。契约写明:①依赖变更必须在 PRD 阶段声明
   (服务器不能现场装);②需要新依赖时发布单含 venv 重建步骤(本机构建上传)
4. **.env 差异清单**(本次实测缺口,部署单必带):
   `SK2_AD_LLM_BASE_URL`/`SK2_AD_LLM_MODEL`(豆包接入点 ep-20260829191419-cjp68)、
   `SK2_ADMIN_*`(admin 口令)、`SK2_AD_DEFAULT_VIDEO_PROVIDER_ID`
   (无 ALI key,默认须 volcengine-seedance)——契约加一条:.env.example 与服务器
   .env 的差异检查进部署冒烟
5. **nginx**:已有 SPA try_files,新版前端路由 /login /admin /mix 零改动兼容——
   前端新增路由免 nginx 变更,写入部署常识

## 非目标

- 不做通用 CI/CD 平台(GitHub Actions/Jenkins 不引入)
- 不做多环境(dev/staging/prod 分级),单环境先行
- 不动现有 release 的合并/tag 语义
