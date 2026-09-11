<script setup lang="ts">
import type { Role } from '../api'
defineProps<{ role: Role }>()
defineEmits<{ (e: 'open', role: Role): void }>()
</script>

<template>
  <div class="desk" :class="role.status" @click="$emit('open', role)">
    <div class="cnt" v-if="role.count">{{ role.count }}</div>
    <div class="avatar"><img :src="role.icon" :alt="role.nick"></div>
    <div class="who">{{ role.nick }}</div>
    <div class="role">{{ role.title }}</div>
    <div class="st"><span class="dot"></span>{{ role.count ? role.count + ' 单进行中' : '空闲' }}</div>
  </div>
</template>

<style scoped>
.desk { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px;
  cursor:pointer; transition:.15s; position:relative; }
.desk:hover { box-shadow:0 2px 10px rgba(0,0,0,.08); transform:translateY(-2px); }
.cnt { position:absolute; top:12px; right:12px; background:var(--run); color:#fff; border-radius:10px;
  padding:1px 8px; font-size:12px; }
.desk.idle .cnt { background:var(--idle); }
.avatar img { width:46px; height:46px; border-radius:10px; display:block; box-shadow:0 2px 6px rgba(0,0,0,.15); }
.desk.active .avatar img { filter:drop-shadow(0 0 6px rgba(37,99,235,.4)); }
.desk.idle .avatar img { opacity:.5; filter:grayscale(.4); }
.who { font-weight:600; margin-top:8px; }
.role { color:var(--mut); font-size:12px; }
.st { margin-top:8px; font-size:12px; color:var(--mut); }
.dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:4px; }
.desk.active .dot { background:var(--ok); }
.desk.idle .dot { background:var(--idle); }
</style>
