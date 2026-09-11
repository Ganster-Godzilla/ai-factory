<script setup lang="ts">
import type { Role } from '../api'
import TicketCardItem from './TicketCardItem.vue'
defineProps<{ role: Role | null }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'open-ticket', id: string): void }>()
</script>

<template>
  <template v-if="role">
    <div class="mask" @click="emit('close')"></div>
    <div class="drawer">
      <button class="close" @click="emit('close')">×</button>
      <h2><img :src="role.icon" :alt="role.nick"> {{ role.nick }} · {{ role.title }}</h2>
      <div class="sub">{{ role.count ? role.count + ' 张工单在处理' : '当前空闲' }}</div>
      <div v-if="!role.tickets.length" class="empty">没有进行中的工单</div>
      <TicketCardItem v-for="c in role.tickets" :key="c.id" :card="c" @open="emit('open-ticket', $event)" />
    </div>
  </template>
</template>

<style scoped>
.mask { position:fixed; inset:0; background:rgba(0,0,0,.25); z-index:9; }
.drawer { position:fixed; top:0; right:0; width:420px; max-width:92vw; height:100%;
  background:var(--card); z-index:10; box-shadow:-4px 0 16px rgba(0,0,0,.12); padding:18px; overflow-y:auto; }
.drawer h2 { font-size:15px; margin:0 0 4px; display:flex; align-items:center; gap:8px; }
.drawer h2 img { width:28px; border-radius:6px; }
.close { position:absolute; top:12px; right:14px; cursor:pointer; color:var(--mut); font-size:20px;
  border:none; background:none; }
.sub { color:var(--mut); font-size:12px; }
.empty { color:var(--mut); text-align:center; padding:30px 0; }
</style>
