<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { fetchOffice, type OfficeData, type Role, type Interaction } from './api'
import RoleDrawer from './components/RoleDrawer.vue'
import TicketCardItem from './components/TicketCardItem.vue'

// public/ 下资源经 base(/static/web/)前缀引用;勿写 /static/... 绝对路径(Vite 会当模块解析报错)
const base = import.meta.env.BASE_URL
const bgUrl = computed(() => base + 'office-scene.png')
// 人物图:后端 icon 给的是文件名(pm.png 等)或 /static/avatars 路径,统一归一到 SPA 产物内 avatars
function roleIcon(r: Role): string {
  const f = r.icon.split('/').pop() || r.icon
  return base + 'avatars/' + f
}

const data = ref<OfficeData>({
  synced_at: '', project: null, projects: [],
  kpi: { running: 0, pending_approval: 0, suspended: 0, today_done: 0, ds_today: 0 },
  roles: [], attention: [], observation: [], interactions: [],
})
const project = ref<string | null>(null)
const cur = ref<Role | null>(null)
const syncError = ref('')
const fallbackRoles: Role[] = [
  ['pm', 'PM', '擎天柱', 'pm.png'], ['architect', '架构师', '千斤顶', 'architect.png'],
  ['dev', '开发', '大黄蜂', 'dev.png'], ['qa', 'QA', '救护车', 'qa.png'],
  ['release', '发布', '铁皮', 'release.png'], ['sre', 'SRE', '爵士', 'sre.png'],
].map(([key, title, nick, icon]) => ({ key, title, nick, icon: `/static/avatars/${icon}`, count: 0, status: 'idle', tickets: [] }))
let timer: number | undefined

async function load() {
  try {
    const next = await fetchOffice(project.value)
    data.value = { ...data.value, ...next, roles: next.roles || [], attention: next.attention || [], observation: next.observation || [], interactions: next.interactions || [] }
    syncError.value = ''
  }
  catch (e) { console.warn('同步失败', e); syncError.value = '数据同步中断，当前显示角色静态布局'; if (!data.value.roles.length) data.value.roles = fallbackRoles }
}
function fmtTime(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
function goTicket(id: string) { window.location.href = '/ticket/' + id }
const anchors: Record<string, [number, number]> = {
  pm: [21, 53], architect: [50, 53], dev: [79, 53], qa: [21, 88], release: [50, 88], sre: [79, 88],
}
function interactionPath(i: Interaction) {
  const a = anchors[i.from] || [50, 50], b = anchors[i.to] || [50, 50]
  const mx = (a[0] + b[0]) / 2
  return `M ${a[0]} ${a[1]} Q ${mx} ${(Math.min(a[1], b[1]) - 12)} ${b[0]} ${b[1]}`
}
function interactionStyle(i: Interaction) {
  const a = anchors[i.from] || [50, 50], b = anchors[i.to] || [50, 50]
  return { left: `${(a[0] + b[0]) / 2}%`, top: `${(a[1] + b[1]) / 2 - 8}%` }
}

onMounted(() => { load(); timer = window.setInterval(load, 5000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="topbar">
      <h1>🏢 AI 编排指挥室 <span class="ver">v0.2</span></h1>
      <select v-model="project" @change="load">
        <option :value="null">全部项目</option>
        <option v-for="p in data.projects" :key="p" :value="p">{{ p }}</option>
      </select>
      <a class="back" href="/">看板</a>
      <span class="sync">同步于 {{ fmtTime(data.synced_at) }} · 5s 轮询</span>
    </header>
    <div v-if="syncError" class="sync-error">{{ syncError }}</div>

    <div class="kpis">
      <div class="kpi"><b>{{ data.kpi.running }}</b><span>运行中</span></div>
      <div class="kpi"><b>{{ data.kpi.pending_approval }}</b><span>待审批</span></div>
      <div class="kpi"><b>{{ data.kpi.suspended }}</b><span>阻塞中</span></div>
      <div class="kpi"><b>{{ data.kpi.today_done }}</b><span>今日完成</span></div>
      <div class="kpi"><b>¥{{ data.kpi.ds_today.toFixed(2) }}</b><span>今日费用</span></div>
    </div>

    <div class="layout">
      <div class="main">
        <!-- 2.5D 场景:背景图 + 六个人物锚点(集成说明 V1,只读) -->
        <div class="office-scene">
          <img class="office-bg" :src="bgUrl" alt="六工位研发办公室">
          <div class="workflow-zone zone-left"><strong>01 · 需求与设计</strong><small>PM → 架构师</small></div>
          <div class="workflow-zone zone-center"><strong>02 · 实现与验证</strong><small>开发 → QA</small></div>
          <div class="workflow-zone zone-right"><strong>03 · 交付与运行</strong><small>发布 → SRE</small></div>
          <div class="workflow-arrow arrow-one">›</div><div class="workflow-arrow arrow-two">›</div>
          <svg class="interaction-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <path v-for="i in (data.interactions || [])" :key="i.id" :d="interactionPath(i)" class="consult-line" />
          </svg>
          <button v-for="i in (data.interactions || [])" :key="i.id + '-bubble'" class="interaction-bubble" :style="interactionStyle(i)" @click="goTicket(i.ticket)">
            <b>会诊</b> {{ i.message }}
          </button>
          <button v-for="r in data.roles" :key="r.key"
                  class="scene-role" :class="[r.status, 'role-' + r.key, { consulting: (data.interactions || []).some(i => i.from === r.key || i.to === r.key) }]"
                  @click="cur = r">
            <img :src="roleIcon(r)" :alt="r.nick">
            <span class="role-label">{{ r.nick }} · {{ r.title }}</span>
            <span v-if="r.count" class="role-count">{{ r.count }}</span>
          </button>
        </div>
        <div class="observation card" v-if="data.observation.length">
          <h3>🛰️ 观察窗 · 待 SRE 出报告 ({{ data.observation.length }})</h3>
          <TicketCardItem v-for="c in data.observation" :key="c.id" :card="c" tone="obs" @open="goTicket" />
        </div>
      </div>

      <aside class="side">
        <div class="card">
          <h3>待你处理 ({{ data.attention.length }})</h3>
          <div v-if="!data.attention.length" class="empty">暂无待办 ✓</div>
          <TicketCardItem v-for="c in data.attention" :key="c.id" :card="c" :tone="c.blocked ? 'blk' : 'warn'" @open="goTicket" />
        </div>
      </aside>
    </div>

    <RoleDrawer :role="cur" @close="cur = null" @open-ticket="goTicket" />
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: var(--bg); }
.sync-error { margin:0 20px 8px; padding:6px 10px; color:#ffd6f7; background:#351747; border:1px solid #d946ef; border-radius:5px; font-size:12px; }
.topbar { display:flex; align-items:center; gap:16px; padding:12px 20px; background:var(--card);
  border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }
.topbar h1 { font-size:16px; margin:0; }
.ver { color:var(--mut); font-size:12px; }
.topbar select { padding:4px 8px; border:1px solid var(--line); border-radius:6px; }
.back { color:var(--run); text-decoration:none; font-size:13px; }
.sync { margin-left:auto; color:var(--mut); font-size:12px; }
.kpis { display:flex; gap:12px; padding:14px 20px; flex-wrap:wrap; }
.kpi { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 16px; min-width:96px; }
.kpi b { display:block; font-size:22px; }
.kpi span { color:var(--mut); font-size:12px; }
.layout { display:grid; grid-template-columns:1fr 320px; gap:16px; padding:0 20px 20px; }

/* ===== 2.5D 场景(集成说明 V1) ===== */
.office-scene { position:relative; width:100%; aspect-ratio:1; overflow:hidden;
  background:#101a35; border-radius:12px; border:1px solid #263b68; }
.office-bg { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
.workflow-zone { position:absolute; top:4%; z-index:2; width:27%; padding:7px 9px; color:#dff8ff; border:1px solid rgba(56,217,255,.7); border-left:3px solid #38d9ff; background:rgba(8,18,40,.82); box-shadow:0 0 18px rgba(56,217,255,.12); }
.workflow-zone strong,.workflow-zone small { display:block; }
.workflow-zone strong { font-size:clamp(9px,1.15vw,13px); letter-spacing:.04em; }
.workflow-zone small { margin-top:2px; color:#f0abfc; font-size:clamp(8px,1vw,11px); }
.zone-left { left:3%; }.zone-center { left:36.5%; }.zone-right { right:3%; }
.workflow-arrow { position:absolute; top:48%; z-index:3; color:#38d9ff; font-size:clamp(26px,4vw,54px); text-shadow:0 0 12px #38d9ff; animation:arrow-pulse 1.4s ease-in-out infinite alternate; }
.arrow-one { left:32.5%; }.arrow-two { left:65.5%; }
.interaction-layer { position:absolute; inset:0; width:100%; height:100%; z-index:3; pointer-events:none; overflow:visible; }
.consult-line { fill:none; stroke:#38d9ff; stroke-width:0.65; stroke-dasharray:2 1.5; filter:drop-shadow(0 0 2px #38d9ff); animation:signal-flow 1.2s linear infinite; }
.interaction-bubble { position:absolute; transform:translate(-50%,-50%); z-index:4; max-width:30%; padding:4px 7px; border:1px solid #38d9ff; border-radius:4px; color:#dff8ff; background:rgba(8,18,40,.92); font-size:clamp(8px,1vw,11px); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:pointer; }
.interaction-bubble b { color:#f0abfc; }
@keyframes signal-flow { to { stroke-dashoffset:-7; } }
@keyframes arrow-pulse { from { opacity:.45; transform:translateX(-3px); } to { opacity:1; transform:translateX(3px); } }
.scene-role { position:absolute; transform:translate(-50%,-100%); width:9.5%;
  min-width:52px; max-width:96px; padding:0; border:0; background:transparent;
  cursor:pointer; z-index:2; transition:filter .2s, opacity .2s; }
.scene-role img { display:block; width:100%; aspect-ratio:1; object-fit:contain;
  filter:drop-shadow(0 8px 8px rgba(0,0,0,.35)); }
.scene-role:hover img { filter:drop-shadow(0 0 10px rgba(37,99,235,.6)); }
.role-label { display:block; margin-top:2px; color:#dff8ff; background:rgba(8,18,40,.9);
  border:1px solid #38d9ff; border-radius:4px; font-size:clamp(9px,1.2vw,12px);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding:2px 5px; }
.role-count { position:absolute; top:0; right:0; border-radius:999px; padding:1px 6px;
  color:#fff; background:var(--run); font-size:11px; }
/* 状态:活跃发光,空闲降透明(不用灰度,保角色配色,集成说明) */
.scene-role.active img { filter:drop-shadow(0 0 12px rgba(56,217,255,.7)); }
.scene-role.consulting img { animation:consult-pulse 1s ease-in-out infinite alternate; }
.scene-role.idle { opacity:.82; }
/* 六工位锚点(相对 1024×1024 背景中心点,两排三列,椅子前方空位) */
.role-pm        { left:21%; top:53%; }
.role-architect { left:50%; top:53%; }
.role-dev       { left:79%; top:53%; }
.role-qa        { left:21%; top:88%; }
.role-release   { left:50%; top:88%; }
.role-sre       { left:79%; top:88%; }
@media (max-width: 720px) { .scene-role { width:13%; } }
@keyframes consult-pulse { from { filter:drop-shadow(0 0 5px #38d9ff); } to { filter:drop-shadow(0 0 16px #d946ef); } }

.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; }
.observation { margin-top:14px; }
.card h3 { margin:0 0 10px; font-size:13px; color:var(--mut); }
.empty { color:var(--mut); text-align:center; padding:30px 0; }
@media (max-width: 980px) { .layout { grid-template-columns:1fr; } }
</style>
