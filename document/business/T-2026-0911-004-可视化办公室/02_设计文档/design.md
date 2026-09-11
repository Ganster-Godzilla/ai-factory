# 设计:可视化办公室 V0.1

- 工单:`pool/tickets/T-2026-0911-004.yaml`
- 阶段:P2 设计
- 类型:feature / 平台体验(本单先做只读闭环,已实现并验证)

## Architecture

后端不动,新增"数据聚合 + 只读 API + 灰盒前端"三层,只读消费 pool,零写入。

```
pool/tickets/*.yaml + *.events.jsonl   ← 现有,不动
   ↓ (只读)
orchestrator/dashboard/office.py       ← 新增:office_data() 聚合
   ├─ 六岗位映射(state→role,ROLES 表:变形金刚命名+SVG 路径)
   ├─ _ticket_card():目标/阶段/最近更新/阻塞/气泡/产物/子任务进度
   ├─ attention(审批中+挂起)+ observation(monitoring 单列)+ KPI
   ↓
orchestrator/dashboard/app.py          ← 新增两路由
   ├─ GET /api/v1/office → jsonify(office_data())  只读,5s 轮询消费
   └─ GET /office → 按原文返回 office.html(不走 Jinja,见坑①)
   ↓
orchestrator/dashboard/templates/office.html  ← 灰盒 SPA(Vue3 CDN 单文件)
   六工位卡(img SVG 头像)+岗位抽屉+待办栏+观察窗区块+KPI+项目切换+5s 轮询
orchestrator/dashboard/static/avatars/*.svg   ← 6 汽车人原创立体简笔头像
```

关键决策:
- **状态真实**:无心跳,只显"阶段+最近更新",不假装在线;_bubble() 把事件
  格式化为"QA:验收失败"等结构化短句,不展示模型推理。
- **观察窗单列**:monitoring 工单独立成 observation 区块,不计入 SRE 工位
  "进行中"(用户指认的语义失真)。
- **只读**:office.py 只调 views/read_events 查询,前端不得据此改状态;
  写操作(审批/建单)走 app.py 现有 /approve、/resume 路由,不在本 API。

## How

1. `office.py`:ROLES 六岗位表 + `_ticket_card` + `office_data` 聚合(只读)。
2. `app.py`:`/api/v1/office`(jsonify)+ `/office`(原文返回,跳过 Jinja)。
3. `office.html`:Vue3 CDN 单文件,六工位卡+抽屉+待办+观察窗+KPI+项目切换+轮询。
4. `static/avatars/`:自绘 6 汽车人立体简笔 SVG(渐变+高光+投影,无版权风险)。
5. 验证:起测试实例 curl 校验 API/页面/头像;坑①②修复(见 Checkpoints)。

## Checkpoints

- [x] /api/v1/office 返回六岗位×工单×KPI×待办×观察窗,与 pool 实况一致
- [x] 六岗位命名(变形金刚)+ 6 SVG 头像全部 200
- [x] monitoring 33 单单列观察窗,SRE 工位显示空闲(语义真实)
- [x] 坑①:/office 不走 Jinja(Vue `{{ }}`+三元符被误解析致 500)→ 原文返回
- [x] 坑②:重启先杀净端口孤儿(双实例旧代码抢流量,HTTP 500/404)
- [x] 只读零写入,SK 项目零干扰
- [ ] 正式视觉稿一张(后续);网页审批/建单(阶段2);前端 SPA 升级(阶段2)

## Rollback

纯新增文件(office.py + office.html + 6 svg)+ app.py 两路由,无 schema/数据迁移,
零业务逻辑改动。回滚 = revert 提交,dashboard 恢复原看板;pool/编排器/SK 全程不受影响。
风险点:Jinja/Vue 语法冲突与端口孤儿——均已实证修复并留注释。
