<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { fetchOffice, type OfficeData, type Role } from './api'
import RoleDesk from './components/RoleDesk.vue'
import RoleDrawer from './components/RoleDrawer.vue'
import TicketCardItem from './components/TicketCardItem.vue'

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
        <div class="office">
          <RoleDesk v-for="r in data.roles" :key="r.key" :role="r" @open="cur = $event" />
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
.office { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; }
.observation { margin-top:14px; }
.card h3 { margin:0 0 10px; font-size:13px; color:var(--mut); }
.empty { color:var(--mut); text-align:center; padding:30px 0; }
@media (max-width: 980px) { .layout { grid-template-columns:1fr; } .office { grid-template-columns:repeat(2,1fr); } }
</style>
