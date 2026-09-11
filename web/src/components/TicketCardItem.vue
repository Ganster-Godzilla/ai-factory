<script setup lang="ts">
import type { TicketCard } from '../api'
defineProps<{ card: TicketCard; tone?: 'warn' | 'blk' | 'obs' }>()
defineEmits<{ (e: 'open', id: string): void }>()
function fmtTime(ts: string) {
  if (!ts) return '-'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="tcard" :class="tone" @click="$emit('open', card.id)">
    <div class="id">{{ card.id }} <span class="proj">{{ card.project }}</span></div>
    <div class="sum">{{ card.summary }}</div>
    <div class="meta">{{ card.state }} · {{ fmtTime(card.last_update) }}</div>
    <div v-if="card.tasks_total" class="prog">子任务 {{ card.tasks_done }}/{{ card.tasks_total }}</div>
    <div v-if="card.blocked" class="blk">⛔ {{ card.blocked }}</div>
    <div v-if="card.bubbles?.length"><span v-for="b in card.bubbles" :key="b" class="bubble">{{ b }}</span></div>
    <div v-if="card.artifacts?.length" class="arts">产物:{{ card.artifacts.join(', ') }}</div>
  </div>
</template>

<style scoped>
.tcard { border:1px solid var(--line); border-radius:10px; padding:10px; margin:10px 0; cursor:pointer; }
.tcard:hover { box-shadow:0 1px 6px rgba(0,0,0,.08); }
.tcard.warn { border-left:3px solid var(--warn); background:#fffaf0; }
.tcard.blk { border-left:3px solid var(--blk); background:#fff5f5; }
.tcard.obs { border-left:3px solid var(--run); background:#f0f6ff; }
.id { font-weight:600; color:var(--run); }
.proj { color:var(--mut); font-weight:400; font-size:12px; }
.sum { font-size:13px; }
.meta { color:var(--mut); font-size:12px; margin:4px 0; }
.prog { font-size:12px; color:var(--ok); }
.blk { color:var(--blk); font-size:12px; }
.bubble { display:inline-block; background:#eef2ff; color:#3730a3; border-radius:10px;
  padding:2px 8px; font-size:12px; margin:2px 4px 0 0; }
.arts { font-size:12px; color:var(--mut); }
</style>
