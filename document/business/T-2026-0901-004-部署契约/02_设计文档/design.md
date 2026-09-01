# 设计-T-2026-0901-004: release 契约补"部署"环节(local/remote 双形态)

> Phase 2 产物。PRD:document/business/T-2026-0901-004-部署契约/01_需求分析/prd.md

## Architecture

```
orchestrator.yaml              新增顶层 deploy: 段,按项目名登记部署配置
                               (projects: 值保持纯路径字符串不动,向后兼容)
orchestrator/daemon/deploy.py  新模块,单一事实源:
                               config 加载校验 / smoke+差异检查 / remote+local 双流水线 /
                               发布记录章节写入 / 失败建 incident / CLI __main__
artifacts.py                   P5_RELEASE 发布记录 require_sections 扩章
                               (合并清单/版本/部署清单/冒烟结果/回滚方案)
plugin/skills/phase5-release/SKILL.md   契约条款:合并→tag→deploy 脚本→冒烟→记录
orchestrator/roles/prompts/release.md   提示词同步新契约+修过时路径(docs/specs→工单文件夹)
docs/deploy-runbook.md         部署手册:五坑情报(sudo/uid/venv/.env/nginx)沉淀(F10)
runner.py                      不改:release 判负已有 suspend+incident 链路;
                               冒烟失败由 deploy 脚本自行建 incident 并非零退出,自然接入
```

deploy target 抽象:**target 只有 local/remote 两形态,差异全部沉淀为配置值**,
代码零分支判断凭证/权限形态。sudo 卡点(F8,待 boss 决策 a/b)不进入代码:
配置里就是一行 `restart_cmd`,决策只改编排配置不改程序——设计上无未决开放问题。

## How

### 1. deploy 配置 schema(orchestrator.yaml 顶层 `deploy:` 段)

```yaml
deploy:
  sk-video-studio:
    target: remote
    host: "deploy@47.109.84.154"
    ssh_key: "~/.ssh/sk-aliyun-47"
    app_dir: "/opt/sk-video-studio"          # 其下 releases/<版本> 逐版留存 + current 软链
    service: "sk-api"
    build_cmd: "npm run build --prefix frontend"   # 前端本地构建 dist(服务器不装 node)
    dist_dir: "frontend/dist"
    requirements: "requirements.txt"         # 依赖差异前置检查基准
    env_example: ".env.example"              # 只比 key 名,值永不回传/入记录
    remote_env: "/opt/sk-video-studio/.env"
    restart_cmd: "sudo -n systemctl restart sk-api"  # sudo 白名单/User=deploy 二选一只改这里
    smoke: ["http://47.109.84.154/api/health", "http://47.109.84.154/"]
  ai-factory:
    target: local
    processes:                               # 合并后自动重启的长驻进程清单(F7)
      - {name: dashboard, pidfile: ".orc-local/dashboard.pid",
         start_cmd: "python -m orchestrator.dashboard.app"}
    smoke: ["http://127.0.0.1:8765/"]
```

校验规则(target/必填键/路径存在性)在加载时完成,非法配置响亮报错。

### 2. remote 流水线(deploy.py,版本=项目仓 `git describe --tags --always`)

1. 本地执行 build_cmd 构建 dist → tar.gz 打包(dist + 后端代码)
2. scp 上传 → ssh 远端:`mkdir releases/<ver> && tar -x && chown -R` uid 归一(F2 坑)
3. **依赖差异前置检查**:本地 requirements 哈希 vs 远端 `releases/current/.requirements.sha`
   不一致即中止 FAIL;发布单显式声明处置时以 `--allow-deps-change` 放行,
   且发布记录必写 venv 重建说明(服务器不现场装依赖,已澄清)
4. **.env 差异检查**:远端只回传 key 名集合(`cut -d= -f1`),与 env_example key 集求差,
   差异清单(仅 key 名)进部署单;值不出现在任何输出/记录/事件流(R9 密钥不落库)
5. `ln -sfn releases/<ver> current` 回切 → 执行 restart_cmd
6. 冒烟(见 §3)→ 写发布记录章节(见 §4)

### 3. 冒烟检查器(F3)

对配置 smoke URL 逐个 GET 期望 200,失败重试 3 次(间隔退避),结果(URL/状态码/耗时)
全量留痕写发布记录"冒烟结果"章节;任一非 200 即整体失败。

### 4. 发布记录章节写入与失败处置(F5)

- 成功:写"部署清单"(版本/目标/时间/依赖与 .env 差异清单)+"冒烟结果"(全绿留痕)
  +"回滚方案"(自动生成可照抄命令:remote=`ln -sfn releases/<上一版> current && <restart_cmd>`;
  local=`git checkout <上一 tag>` + 进程重启)
- 失败:`new_ticket(type=incident, related_ticket=<原单>)` + 原单事件流
  `incident_created` 回链 + 发布记录写失败详情与回滚说明 + **退出码非零**——
  release 角色(dsh)判负走既有 `release_failed` 挂起,不静默放行
- 未登记 deploy 配置的项目:部署清单章节写"未登记 deploy,本单纯代码交付"显式声明,
  章节仍在(门禁统一,语义由审批人复核)

### 5. local 流水线(F7)

按 processes 清单逐个重启(pidfile 读 pid → terminate → spawn start_cmd 并回写 pid)
→ 本地 smoke → 写发布记录。治"合并后忘重启"病根:重启动作在脚本里,不靠人记得。

### 6. 门禁扩章

artifacts.py P5_RELEASE require_sections:
`["合并清单", "版本", "部署清单", "冒烟结果", "回滚方案"]`。
影响面:对在途工单,release 时按新契约执行(契约扩条款即日本意);
存量单(created_at 为空)仍不追溯(D3 不变)。

## 数据设计

无持久化 schema 变更。orchestrator.yaml 增顶层 `deploy:` 段(新键,既有读取方不受影响);
发布记录新增三个章节(纯文档);服务器侧 `releases/<ver>` 目录与 current 软链为部署产物。

## 接口契约

| 面 | 变更 |
|---|---|
| `load_deploy_config(cfg, project) -> dict \| None` | 新增;None=未登记 |
| `smoke(urls, expect=200, retries=3) -> list[SmokeResult]` | 新增,纯函数可测 |
| `env_key_diff(example_path, remote_keys) -> list[str]` | 新增,仅 key 名 |
| `run_deploy(pool, cfg, ticket, project_dir, allow_deps_change=False) -> int` | 新增;0=全绿 |
| CLI `python -m orchestrator.daemon.deploy <tid> [--allow-deps-change]` | 新增;release 角色与人工共用同一入口 |
| ARTIFACT_MANIFEST["P5_RELEASE"].require_sections | 扩三章 |
| 状态机/台账/runner | 不变 |

## Checkpoints

1. deploy.py 各单元用例全绿(config 校验/smoke 重试/env+deps 差异/remote 命令序列
   fake 断言/local pidfile 重启/记录写入/incident 建单)
2. P5 门禁新章节生效(test_artifacts_manifest 断言)+ 本单 release 时 dogfood
3. local 形态演示:CLI 重启 dashboard + 本地冒烟全绿;失败路径演示:
   登记一个 404 冒烟 URL → incident 自动建成 + 回滚说明可照抄
4. remote 形态演示(sk-video-studio):构建→上传→重启→/api/health 与关键路由 200→前端 200
5. 全量 pytest 绿 + pyflakes 净 + `python scripts/check-pool-load.py` 0 bad

## Rollback

纯新增:一个模块 + 一段配置 + 文档章节,代码 revert 即回;
P5 门禁回退 = artifacts.py 恢复旧 require_sections。
服务器侧已部署内容不受本仓回滚影响(本单不改 sk 仓代码);
releases/<ver> 逐版留存本身就是 remote 回滚机制,删除本单不影响其存在。

## 测试用例设计映射

| 功能清单 | 测试 |
|---|---|
| F1 target 抽象/配置登记 | test_deploy_config.py(双形态加载/缺键报错/未登记 None) |
| F2 remote 脚本化/uid 归一/依赖前置 | test_deploy_remote.py(fake runner 断言命令序列含 chown/deps 中止) |
| F3 冒烟留痕 | test_deploy_smoke.py(本地 HTTP fixture:全 200/重试/非 200 判负) |
| F4 回滚说明生成 | test_deploy_record.py(回滚方案章节含上一版回切命令) |
| F5 失败建 incident 不静默 | test_deploy_record.py(tmp pool 断言 incident 单+回链+非零退出) |
| F6 .env 差异仅 key 名 | test_deploy_smoke.py(差异清单无 value 断言) |
| F7 local 进程重启 | test_deploy_local.py(pidfile kill+spawn 断言) |
| F8 sudo 卡点 | 设计消解:restart_cmd 配置化,无代码分支;配置值待 boss 决策 |
| F9 双形态演示 | 演示记录 doccheck(G7/G8) |
| F10 部署常识沉淀 | docs/deploy-runbook.md doccheck(G6) |
