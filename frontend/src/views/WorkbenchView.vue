<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, formatTime, toTimeInput } from '../api'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { labelFor, TASK_PRIORITIES, TASK_STATUSES, TASK_TYPES } from '../uiLabels'
import type { Interview, Job, Task, TaskSuggestion } from '../types'

defineEmits<{ openApplications: [] }>()
type FunnelStage = { stage: string; count: number; share: number }
type Overview = {
  timezone: string; counts: Record<string, number>; application_statuses: Record<string, number>
  application_funnel: FunnelStage[]; outcomes: Record<string, number>
  upcoming_interviews: Interview[]; recent_interviews: Interview[]; overdue_tasks: Task[]
  tasks: Task[]; favorite_jobs: Job[]
}

const data = ref<Overview | null>(null)
const suggestions = ref<TaskSuggestion[]>([])
const error = ref('')
const accepting = ref('')
const task = reactive({ title: '', task_type: 'GENERAL', priority: 'P2', due_at: '', description: '' })
const editingTask = ref<Task | null>(null)
const editForm = reactive({ title: '', description: '', task_type: 'GENERAL', status: 'TODO', priority: 'P2', due_at: '' })
const funnelMax = computed(() => Math.max(1, ...(data.value?.application_funnel.map(item => item.count) || [1])))

async function load() {
  try {
    const [overview, suggestionResult] = await Promise.all([
      api.get<Overview>('/api/workbench'),
      api.get<{ config: { version: string }; items: TaskSuggestion[] }>('/api/task-suggestions'),
    ])
    data.value = overview
    suggestions.value = suggestionResult.items
    error.value = ''
  } catch (reason) { error.value = (reason as Error).message }
}

async function acceptSuggestion(item: TaskSuggestion) {
  accepting.value = item.suggestion_key
  try { await api.post(`/api/task-suggestions/${item.suggestion_key}/accept`); await load() }
  catch (reason) { error.value = (reason as Error).message }
  finally { accepting.value = '' }
}

async function createTask() {
  if (!task.title.trim()) return
  await api.post('/api/tasks', { ...task, status: 'TODO' })
  Object.assign(task, { title: '', task_type: 'GENERAL', priority: 'P2', due_at: '', description: '' })
  await load()
}

function startEdit(item: Task) {
  editingTask.value = item
  Object.assign(editForm, { title: item.title, description: item.description, task_type: item.task_type, status: item.status, priority: item.priority, due_at: toTimeInput(item.due_at) })
}

async function saveTask() {
  const item = editingTask.value
  if (!item) return
  await api.patch(`/api/tasks/${item.task_id}`, { ...editForm, version: item.version, job_id: item.job_id, application_id: item.application_id, interview_round_id: item.interview_round_id })
  editingTask.value = null
  await load()
}

async function changeTaskStatus(item: Task, status: 'DONE' | 'CANCELLED') {
  await api.patch(`/api/tasks/${item.task_id}`, { ...item, status, version: item.version })
  if (editingTask.value?.task_id === item.task_id) editingTask.value = null
  await load()
}

onMounted(load)
</script>

<template>
  <header class="page-header"><div><h1>今日工作台</h1><p>集中查看投递、面试和今天真正需要推进的事情。</p></div><button class="secondary" @click="load">刷新</button></header>
  <p v-if="error" class="error">{{ error }}</p>
  <template v-if="data">
    <section class="metric-grid">
      <article><small>已收藏岗位</small><strong>{{ data.counts.favorites }}</strong><span>共 {{ data.counts.jobs }} 个岗位</span></article>
      <article><small>投递记录</small><strong>{{ data.counts.applications }}</strong><button class="link" @click="$emit('openApplications')">查看看板 →</button></article>
      <article :class="{ 'risk-card': data.counts.overdue_tasks }"><small>逾期待办</small><strong>{{ data.counts.overdue_tasks }}</strong><span>开放待办 {{ data.counts.open_tasks }} 条</span></article>
      <article><small>近期面试</small><strong>{{ data.counts.upcoming_interviews }}</strong><span>{{ data.timezone }}</span></article>
    </section>

    <section class="panel suggestion-panel">
      <div class="panel-title"><div><h2>建议任务</h2><p>建议不会自动写入，点击保留后才成为普通可编辑待办。</p></div><span>{{ suggestions.length }} 条待确认</span></div>
      <EmptyState v-if="!suggestions.length" title="当前没有新建议" note="已保留的建议不会重复出现。" />
      <div class="suggestion-grid"><article v-for="item in suggestions" :key="item.suggestion_key" class="suggestion-card"><div><StatusBadge :value="item.task_preview.priority" /><span class="source-chip">{{ item.source.type }}</span></div><strong>{{ item.task_preview.title }}</strong><p>{{ item.task_preview.description }}</p><small>建议截止 {{ formatTime(item.task_preview.due_at) }} · {{ item.trace.rule }}</small><button class="primary" :disabled="accepting === item.suggestion_key" @click="acceptSuggestion(item)">{{ accepting === item.suggestion_key ? '保留中…' : '保留为待办' }}</button></article></div>
    </section>

    <div class="insight-grid">
      <section class="panel"><div class="panel-title"><h2>投递漏斗</h2><span>当前状态分布</span></div><div class="funnel-list"><div v-for="item in data.application_funnel" :key="item.stage" class="funnel-row"><StatusBadge :value="item.stage" /><div><span :style="{ width: `${Math.max(5, item.count / funnelMax * 100)}%` }"></span></div><strong>{{ item.count }}</strong></div></div><small class="panel-note">拒绝 {{ data.outcomes.REJECTED || 0 }} · 主动撤回 {{ data.outcomes.WITHDRAWN || 0 }}</small></section>
      <section class="panel"><div class="panel-title"><h2>近期面试</h2><span>{{ data.recent_interviews.length }} 场</span></div><EmptyState v-if="!data.recent_interviews.length" title="暂无面试安排" note="在投递进度页添加面试轮次。" /><div v-for="item in data.recent_interviews" :key="item.round_id" class="timeline-item"><span></span><div><strong>{{ item.title }}</strong><small>{{ formatTime(item.scheduled_at) }}</small><StatusBadge :value="item.status" /></div></div></section>
      <section class="panel"><div class="panel-title"><h2>逾期待办</h2><span>{{ data.overdue_tasks.length }} 条</span></div><EmptyState v-if="!data.overdue_tasks.length" title="没有逾期待办" note="当前时间风险已清空。" /><button v-for="item in data.overdue_tasks" :key="item.task_id" class="overdue-row" @click="startEdit(item)"><span><strong>{{ item.title }}</strong><small>{{ formatTime(item.due_at) }}</small></span><StatusBadge :value="item.priority" /></button></section>
    </div>

    <section class="panel task-panel">
      <div class="panel-title"><h2>全部待办</h2><span>{{ data.tasks.length }} 条</span></div>
      <form class="quick-add" @submit.prevent="createTask"><label class="task-title-field">待办事项<input v-model="task.title" placeholder="例如：准备阿里技术一面" required /></label><label>优先级<select v-model="task.priority"><option v-for="item in TASK_PRIORITIES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label>截止时间<input v-model="task.due_at" type="datetime-local" /></label><button class="primary">添加</button></form>
      <EmptyState v-if="!data.tasks.length" title="当前没有待办" note="先添加一件今天要推进的事。" />
      <div v-for="item in data.tasks" :key="item.task_id" class="task-row"><button class="check" :class="{ done: item.status === 'DONE' }" :disabled="item.status === 'DONE' || item.status === 'CANCELLED'" @click="changeTaskStatus(item, 'DONE')">✓</button><div><strong>{{ item.title }} <span v-if="item.origin === 'SUGGESTED'" class="source-chip">建议保留</span></strong><small>{{ formatTime(item.due_at) }} · {{ labelFor(item.status) }}</small></div><StatusBadge :value="item.priority" /><div class="row-actions"><button class="mini" @click="startEdit(item)">编辑</button><button v-if="item.status !== 'CANCELLED' && item.status !== 'DONE'" class="mini danger-text" @click="changeTaskStatus(item, 'CANCELLED')">取消</button></div></div>
      <form v-if="editingTask" class="inline-editor" @submit.prevent="saveTask"><div class="panel-title"><div><h3>编辑待办</h3><p v-if="editingTask.origin === 'SUGGESTED'">这条待办来自系统建议，仍可正常修改。</p></div><button type="button" class="ghost-dark" @click="editingTask = null">关闭</button></div><div class="form-grid"><label>标题<input v-model="editForm.title" required /></label><label>截止时间<input v-model="editForm.due_at" type="datetime-local" /></label><label>类型<select v-model="editForm.task_type"><option v-for="item in TASK_TYPES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label>优先级<select v-model="editForm.priority"><option v-for="item in TASK_PRIORITIES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label>状态<select v-model="editForm.status"><option v-for="item in TASK_STATUSES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label class="wide">说明<textarea v-model="editForm.description" rows="3"></textarea></label></div><div class="form-actions"><button type="button" class="danger" @click="editForm.status = 'CANCELLED'; saveTask()">取消待办</button><button class="primary">保存修改</button></div></form>
    </section>
  </template>
</template>
