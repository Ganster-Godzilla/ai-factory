<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { fetchOffice, type OfficeData, type Role } from './api'
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
  roles: [], attention: [], observation: [],
})
const project = ref<string | null>(null)
const cur = ref<Role | null>(null)
let timer: number | undefined

async function load() {
  try { data.value = await fetchOffice(project.value) }
  catch (e) { console.warn('同步失败', e) }
}
function fmtTime(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
function goTicket(id: string) { window.location.href = '/ticket/' + id }

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
          <button v-for="r in data.roles" :key="r.key"
                  class="scene-role" :class="[r.status, 'role-' + r.key]"
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
  background:#e8e0d2; border-radius:12px; border:1px solid var(--line); }
.office-bg { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }
.scene-role { position:absolute; transform:translate(-50%,-50%); width:15%;
  min-width:64px; max-width:130px; padding:0; border:0; background:transparent;
  cursor:pointer; z-index:2; transition:filter .2s, opacity .2s; }
.scene-role img { display:block; width:100%; aspect-ratio:1; object-fit:contain;
  filter:drop-shadow(0 8px 8px rgba(0,0,0,.35)); }
.scene-role:hover img { filter:drop-shadow(0 0 10px rgba(37,99,235,.6)); }
.role-label { display:block; margin-top:2px; color:#1f2937; background:rgba(255,255,255,.88);
  border:1px solid var(--line); border-radius:6px; font-size:clamp(9px,1.2vw,12px);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding:2px 5px; }
.role-count { position:absolute; top:0; right:0; border-radius:999px; padding:1px 6px;
  color:#fff; background:var(--run); font-size:11px; }
/* 状态:活跃发光,空闲降透明(不用灰度,保角色配色,集成说明) */
.scene-role.active img { filter:drop-shadow(0 0 12px rgba(56,217,255,.7)); }
.scene-role.idle { opacity:.65; }
/* 六工位锚点(相对 1024×1024 背景中心点,两排三列,椅子前方空位) */
.role-pm        { left:21%; top:39%; }
.role-architect { left:50%; top:39%; }
.role-dev       { left:79%; top:39%; }
.role-qa        { left:21%; top:70%; }
.role-release   { left:50%; top:70%; }
.role-sre       { left:79%; top:70%; }
@media (max-width: 720px) { .scene-role { width:19%; } }

.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; }
.observation { margin-top:14px; }
.card h3 { margin:0 0 10px; font-size:13px; color:var(--mut); }
.empty { color:var(--mut); text-align:center; padding:30px 0; }
@media (max-width: 980px) { .layout { grid-template-columns:1fr; } }
</style>
