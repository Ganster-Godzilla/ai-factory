# AI Factory 办公室场景集成说明

## 素材

- 场景：`orchestrator/dashboard/static/office-scene.png`
- 角色：`orchestrator/dashboard/static/avatars/pm.png`、`architect.png`、`dev.png`、`qa.png`、`release.png`、`sre.png`
- 后端角色数据已在 `orchestrator/dashboard/office.py` 指向六个 PNG。

## 页面结构

将 `orchestrator/dashboard/templates/office.html` 当前的 `.office` 卡片网格改成一个固定比例场景容器：

```html
<div class="office-scene">
  <img class="office-bg" src="/static/office-scene.png" alt="六工位赛博朋克研发办公室">
  <button v-for="r in data.roles" :key="r.key"
          class="scene-role" :class="[r.status, 'role-' + r.key]"
          @click="open(r)">
    <img :src="r.icon" :alt="r.nick">
    <span class="role-label">{{ r.nick }} · {{ r.title }}</span>
    <span v-if="r.count" class="role-count">{{ r.count }}</span>
  </button>
</div>
```

```css
.office-scene { position:relative; width:100%; aspect-ratio:1; overflow:hidden;
  background:#101a35; }
.office-bg { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
.scene-role { position:absolute; transform:translate(-50%,-50%); width:15%;
  min-width:64px; max-width:130px; padding:0; border:0; background:transparent;
  cursor:pointer; z-index:2; }
.scene-role img { display:block; width:100%; aspect-ratio:1; object-fit:contain;
  filter:drop-shadow(0 8px 8px rgba(0,0,0,.5)); }
.role-label { display:block; margin-top:2px; color:#dff8ff; background:rgba(8,18,40,.85);
  border:1px solid #38d9ff; font-size:clamp(9px,1.2vw,13px); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; padding:2px 5px; }
.role-count { position:absolute; top:0; right:0; border-radius:999px; padding:1px 5px;
  color:#fff; background:#e943c4; font-size:11px; }
```

## 六个工位锚点

坐标是相对于 1024×1024 背景的中心点，使用百分比定位。角色放在椅子前方的空位，不要盖住显示器：

```css
.role-pm        { left:21%; top:39%; }
.role-architect { left:50%; top:39%; }
.role-dev       { left:79%; top:39%; }
.role-qa        { left:21%; top:70%; }
.role-release   { left:50%; top:70%; }
.role-sre       { left:79%; top:70%; }
```

这些坐标对应背景的两排三列工位。不要用 `background-size:cover`，否则背景被裁剪后角色会错位；使用 `object-fit:contain` 或让容器保持 `aspect-ratio:1`。移动端把角色宽度降到 18% 到 20%，并保留横向滚动或全场景缩放，不要改成六张普通卡片。

## 状态与交互

- `r.status` 继续沿用后端的 `active` / `idle`，不要改变工单状态语义。
- 活跃角色可以增加青蓝外发光；空闲角色降低透明度到 `0.65`，不要使用灰度以免破坏角色配色。
- 点击角色继续打开现有详情抽屉，保留工单、气泡、产物信息。
- 场景背景是静态资源，不要每 5 秒重新下载；只有 `/api/v1/office` 数据轮询。

## 验收

桌面和手机都检查：六个角色各自落在一张桌前、没有漂浮到墙上、没有被裁切、标签不互相覆盖；背景中六张桌/六台显示器/六把椅子仍可辨认；点击每个角色能打开原有详情抽屉。
