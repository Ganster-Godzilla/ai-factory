# PRD:release 契约补"部署"环节(CI/CD 缺口治本)

## Why

- 发布≠上线已被实锤:003/004 发布一夜,服务器 /api/store-profiles、/api/login 仍 404,
  部署全靠人记得手工兜底——人忘一次,线上就假死一夜(boss 2026-09-01 抓出)
- 没有云服务器时 CI/CD 也必须成立:deploy target 抽象后,local(ai-factory 自身)
  与 remote(sk-video-studio)走同一份契约,缺口治本而非打补丁
- 首次部署实战已暴露五个确定性坑(sudo/uid/venv/.env/nginx),不写成契约条款,
  下次发布必然重踩

## What

1. **deploy 步骤脚本化**:任一登记了 deploy 配置的项目,release 时自动执行部署,
   不依赖人记得。remote 形态:前端本地构建 dist → tar+ssh 标准路径上传 →
   解包(留存上一版包)→ 服务重启;后端依赖差异部署前检查,有差异必须在发布单
   显式声明处置方式(服务器不能现场装新依赖)
2. **部署后健康检查冒烟**:每个项目登记冒烟清单(/api/health + 本次发布关键新路由 +
   前端入口),全部 200 才算发布成功;冒烟结果留痕进发布记录
3. **回滚说明**:remote 逐版留存上一版包,回滚=回切上一版 + 重启,步骤写进发布记录
   可照抄执行;local 回滚=git tag 回切 + 进程重启
4. **.env 管理约定**:密钥不落库;部署冒烟含 .env.example 与服务器 .env 的差异检查,
   差异清单进部署单必带项
5. **冒烟失败处置**:自动建 incident 工单 + 给出回滚说明,不静默放行
6. **local 形态**:合并后自动重启登记的本地长驻进程(治"合并后忘重启"的根),
   冒烟本地端口

## 验收标准

- 任一 feature 工单走 release 时,deploy 按契约自动执行(全程零手工 ssh/scp)
- local target(ai-factory 自身)演示一次:合并后长驻进程自动重启 + 本地冒烟全绿
- remote target(sk-video-studio)演示一次:构建 → 上传 → 重启 →
  /api/health 与关键路由冒烟全 200 + 前端 200
- 冒烟失败路径演示一次:incident 工单自动建成 + 回滚说明可照抄回切上一版
- 部署单含 .env 差异清单;密钥不出现在仓库与发布记录明文
- 发布记录含回滚方案章节,boss 复核"回滚方案可执行"通过
- pytest 全绿 + `python scripts/check-pool-load.py` 0 bad
