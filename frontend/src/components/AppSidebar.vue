<script setup lang="ts">
import { computed } from 'vue'

type Page = 'workbench' | 'jobs' | 'applications' | 'candidate' | 'agent' | 'agentops'
const props = defineProps<{ page: Page; username: string; role: string }>()
defineEmits<{ select: [page: Page]; logout: [] }>()

const allItems: Array<{ id: Page; label: string; icon: string; adminOnly?: boolean }> = [
  { id: 'workbench', label: '今日工作台', icon: '◫' },
  { id: 'jobs', label: '岗位中心', icon: '◇' },
  { id: 'applications', label: '投递追踪', icon: '◎' },
  { id: 'candidate', label: '候选人 360', icon: '○' },
  { id: 'agent', label: 'Career Agent', icon: '✦' },
  { id: 'agentops', label: 'AgentOps', icon: '⌁', adminOnly: true },
]
const items = computed(() => allItems.filter(item => !item.adminOnly || props.role === 'admin'))
</script>

<template>
  <aside class="sidebar">
    <div class="brand"><div class="brand-mark">O</div><div><b>OfferFlow</b><small>秋招求职工作台</small></div></div>
    <nav>
      <button v-for="item in items" :key="item.id" :class="{ active: page === item.id }" @click="$emit('select', item.id)">
        <span>{{ item.icon }}</span>{{ item.label }}
      </button>
    </nav>
    <div class="sidebar-user"><div><small>当前账号</small><strong>{{ username }}</strong></div><button class="ghost" @click="$emit('logout')">退出</button></div>
  </aside>
</template>
