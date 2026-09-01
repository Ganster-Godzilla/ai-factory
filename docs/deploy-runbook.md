# 部署手册(Deploy Runbook)

> 部署常识沉淀(T-2026-0901-004 F10)。首次部署实战(2026-09-01,sk-video-studio,
> 服务器 47.109.84.154)踩出的五个确定性坑,逐条转为契约条款或部署单必带项。
> 机器执行的部署流水线见 `orchestrator/daemon/deploy.py`,本手册是"为什么这样设计"的常识层。

## 适用形态

- **remote**:云服务器项目(sk-video-studio)。本地构建 → tar+ssh 上传 → 解包留版 →
  uid 归一 → 依赖/.env 前置检查 → current 回切 → restart_cmd 重启 → 冒烟。
- **local**:ai-factory 自身。合并后按 processes 清单重启长驻进程 → 本地冒烟。
- 任一形态走同一契约:发布记录必含 合并清单/版本/部署清单/冒烟结果/回滚方案。

## sudo 卡点

**症状**:服务以 root 跑,deploy 账户无免密 sudo,重启只能干瞪眼。
**解**:契约二选一,配置里就是一行 `restart_cmd`,决策只改编排配置不改程序——
① sudoers 单条 NOPASSWD 白名单(`deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart sk-api`,推荐);
② 或服务改 `User=deploy`。
**实况补记**:部署收官曾用 deploy 账户 passwd -S=L 锁定、绕行 `ssh -tt + su - root`;
该做法遗留 root SSH `PermitRootLogin yes` 隐患——契约收编必须回改
(sudoers 单条 NOPASSWD + `PermitRootLogin no`)。

## uid 穿透

**症状**:本机 tar 打包保留本机 uid(如 197609),解包后服务器 deploy 账户不可写,
部署即失败。
**解**:发布脚本解包后必须 `chown -R deploy <app_dir>`(或 tar 打包时 `--owner` 归一)。
uid 归一写入 remote 流水线固定步骤,不靠人记得。

## venv 策略

**症状**:服务器缺 python3-venv/ensurepip,新 venv 根本建不了;现场装依赖等于现场编译。
**解**:①依赖变更必须在 PRD 阶段声明(服务器不能现场装新依赖);
②确需新依赖时,发布单必须含 venv 重建步骤(本机构建 venv 后随包上传),
deploy 脚本对依赖差异做前置检查,不一致即中止;显式声明处置方式(`--allow-deps-change`)
放行时,发布记录必写 venv 重建说明。

## .env 差异清单

**原则**:密钥不落库——值永不回传/入记录/进事件流,只比 key 名。
**解**:`.env.example` 与服务器 `.env` 的 key 集合差异检查进部署冒烟
(远端只回传 `cut -d= -f1` 的 key 名),差异清单(仅 key 名)进部署单必带项。
**实战实测缺口示例**:`SK2_AD_LLM_BASE_URL`/`SK2_AD_LLM_MODEL`(豆包接入点)、
`SK2_ADMIN_*`(admin 口令)、`SK2_AD_DEFAULT_VIDEO_PROVIDER_ID`
(无 ALI key 时默认须 volcengine-seedance)——这类差异不检查,新部署必然静默错配。

## nginx SPA 路由免改

**常识**:已配置 SPA `try_files` 的站点,前端新增路由(/login /admin /mix 等)
零 nginx 变更即可访问——路由回退到 index.html 是前端职责,不是 nginx 职责。
**解**:前端新增路由免改 nginx,写入部署常识;部署后仍须按冒烟硬规从真实浏览器验证
(见下),因为 curl 拿到 index.html 的 200 不代表页面真的渲染。

## 冒烟两条硬规(外网白屏坑沉淀)

1. **构建时查 API base 约定**:dist 构建把 API base 钉死 127.0.0.1 → 外网白屏。
   构建前必须核对 `VITE_API_BASE_URL` 约定(默认同源,`fetchMe` 按未登录处理),
   禁止把本机地址编进产物。
2. **部署后从非部署机真实浏览器验证**:curl 200 验不出白屏——只证明 HTTP 通,
   不证明页面渲染。冒烟清单除 `/api/health` 与关键新路由外,前端入口必须由
   非部署机的真实浏览器验证。
3. **current 软链是服役命门(2026-09-01 手工换装事故实证)**:systemd unit 的
   WorkingDirectory 指向 `current/apps/api`,nginx root 指向 `current/apps/web/dist`
   ——任何手工换装(绕开契约直接覆盖目录)必须同步维护 `current` 软链,
   软链悬空 = 服务 CHDIR 死循环。冒烟清单加:部署后 `systemctl status <service>`
   (Active=active 且进程 cwd 经 `readlink /proc/<pid>/cwd` 指向 releases/<ver>)
   + curl 双查;事故恢复=`ln -sfn . current` 回兜底或指回上一 releases/<prev>。
