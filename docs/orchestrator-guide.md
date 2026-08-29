# AI 工厂编排器使用说明

> 版本:M4(2026-08-27)。面向:老板(你)。
> 设计规格:[2026-08-19-dual-harness-orchestrator-design.md](superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md)

## 一句话概念

你是一个数字团队的老板。**工单**是任务的唯一载体,在 `pool/tickets/` 里;**角色**(PM/架构师/开发/QA/发布员/SRE)是不同模型扮演的执行者;**你只做审批**,在 Dashboard 上点按钮。

模型分工:k3(包月,贵)= PM/架构师/会诊;DeepSeek/GLM(按量,便宜)= 开发/QA/发布/巡检。

## 每日工作流

### 1. 启动(每次开机)

```bash
# ① 模型网关(k3 共享池,计划任务已常驻;确认在跑)
curl http://127.0.0.1:8787/__status

# ② 启动 Dashboard(在 ai-factory 目录下)
cd /d/workspace/ai-factory
python -m orchestrator.daemon.cli dashboard
# 浏览器打开 http://127.0.0.1:8321
```

### 2. 你的主界面

| 页面 | 干什么 |
|---|---|
| **总览** `/` | k3 周水位、DeepSeek 今日/本月现金、待审批数、运行中、今日事件 |
| **审批中心** `/approvals` | 你的主战场:P0 提案/P1 需求/P2 设计/P5 发布/探针草稿/挂起,点按钮即可 |
| **工单详情** `/ticket/<id>` | 任务进度、事件流、成本 |

### 3. 一张工单的一生(你要做的只有 4 次点击)

```
① P0 提案     → 审批中心点【批准】   (值不值得做)
② P1 需求     → 点【批准】           (PRD 行不行)
③ P2 设计     → 点【批准】           (方案对不对;可【驳回】打回重做)
④ P5 发布     → 点【批准】           (合 main)
   其余全程自动:开发 TDD → QA 黑盒 → 观察窗 → done
   异常 → 工单变红(挂起)→ 你处置后点【恢复】
```

> **产物门禁(T-2026-0829-001,新工单起生效)**:批准前系统会机器校验该阶段产物
> (存在/非空/必含章节/契约),不合格时批准会 409 并列出 FAIL 清单——按清单补齐产物再点。
> 挂起原因 `artifact_missing` = 产物门禁未过,事件流里有 missing 明细;
> 补救后点【恢复】。注意:门禁读项目目录当前分支,产物在工单分支上时审批前别切走。
> 存量工单(无 created_at)不受门禁约束;incident 事故单全豁免。

### 4. CLI(等价操作,备用)

```bash
python -m orchestrator.daemon.cli new quant-lab "给报表加缓存"   # 建工单
python -m orchestrator.daemon.cli list                           # 列表
python -m orchestrator.daemon.cli show T-2026-0827-001           # 详情+事件流
python -m orchestrator.daemon.cli approve <id>                   # 批准(自动识别审批点)
python -m orchestrator.daemon.cli reject <id>                    # 驳回
python -m orchestrator.daemon.cli advance <id> <项目目录>         # 推进一步(真实模型)
python -m orchestrator.daemon.cli advance <id> . --fake          # 假模型演练(不烧钱)
python -m orchestrator.daemon.cli advance <id> . --fake --consult-fake  # 失败演练也不烧 k3
```

## 密钥与网关

- 全部 key 在 `D:\Tool\keys\`:k3-a.env / k3-b.env(k3 共享池)/ deepseek.env / glm.env
- **不要在任何项目目录、git 仓库、聊天里放 key**
- 网关(D:\Tool\kimi-relay.js,端口 8787)管 k3 双 key  failover 和周水位;`/__stats` 看用量
- DeepSeek/GLM 由 dsh 直连,不经过网关
- 换模型:编辑 `orchestrator.yaml` 的 `models:` 段(如 dev 切 glm-5.3-flash 做对照)

## 成本刹车(自动,无需操作)

| 刹车 | 触发 | 结果 |
|---|---|---|
| k3 周配额闸 | 池子周用量超 `k3_week_token_budget`(200 万) | 会诊通道关闭(仅事故单可用) |
| DS 日现金线 | 当日 DeepSeek 消费超 ¥30 | 停止派发新任务 |
| 工单现金帽 | 单工单 DeepSeek 消费超 ¥10 | 工单挂起 |
| 熔断阶梯 | 任务失败:重试 3 次 → k3 会诊 1 次 → 判负 | 3 个任务判负 → 整单挂起 |

阈值都在 `orchestrator.yaml` 的 `budgets:` 段,改阈值走 git 提交留痕。

## 接入新项目(如 SK-main)

```bash
# ① 项目初始化(在项目目录,ai-factory 插件启用状态下)
#    Claude Code 里运行: /ai-factory:ai-init

# ② 登记到编排器:编辑 orchestrator.yaml
projects:
  orc-e2e: d:/workspace/tmp/orc-e2e
  SK-main: d:/workspace/SK-main     # 按实际路径

# ③ 建第一张工单
python -m orchestrator.daemon.cli new SK-main "你的第一个需求"
```

注意:M4 版本的 `advance` 仍需手传项目目录(F4 已在 M5 清单,将支持从 projects 自动解析)。

## 故障处理

| 症状 | 处理 |
|---|---|
| 工单挂起(红色) | 看详情页事件流找原因;修复后审批中心点【恢复】 |
| 会诊反复失败 | 大概率是设计/切片问题,驳回 P2 让架构师重做 |
| `pool/.lock` 残留(建单报 TimeoutError) | 删掉 `pool/.lock` 文件(上次进程被强杀的痕迹) |
| 网关连不上 | `curl http://127.0.0.1:8787/__status`;死了就 `cd /d/Tool && node kimi-relay.js &` |
| dsh 报 key 未填 | 检查 `D:\Tool\keys\deepseek.env` 格式 `KEY=sk-...` |
| github push 失败 | 网络抖动,等会儿重试;必要时开代理(127.0.0.1:7897) |

## 目录速查

```
ai-factory/
├── orchestrator.yaml      ← 平台配置(阈值/项目/模型)
├── pool/                  ← 运行时(gitignore):工单/事件/台账
├── orchestrator/
│   ├── daemon/            ← 状态机/执行器/熔断/台账/CLI
│   ├── adapters/          ← claude -p / dsh 适配器
│   ├── dashboard/         ← 看板(Flask)
│   └── roles/prompts/     ← 角色人设
└── plugin/                ← ai-factory 插件(分发给各项目)
```
