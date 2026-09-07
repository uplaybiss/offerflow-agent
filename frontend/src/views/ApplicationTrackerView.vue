<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, commandId, formatTime, toTimeInput } from '../api'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { Application, Interview, Job } from '../types'

const apps = ref<Application[]>([])
const jobs = ref<Job[]>([])
const interviews = ref<Interview[]>([])
const selected = ref<Application | null>(null)
const editingInterview = ref<Interview | null>(null)
const error = ref('')
const createForm = reactive({ job_id: '', status: 'PLANNED', next_action: '', notes: '' })
const transitionForm = reactive({ next_action: '', notes: '' })
const interviewForm = reactive({ title: '技术面试', round_type: 'TECHNICAL', status: 'SCHEDULED', scheduled_at: '', notes: '' })
const interviewEdit = reactive({ title: '', round_type: 'TECHNICAL', status: 'SCHEDULED', scheduled_at: '', notes: '', result: '' })
const order = ['PLANNED', 'APPLIED', 'ASSESSMENT', 'INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN']
const allowed: Record<string, string[]> = {
  PLANNED: ['APPLIED', 'WITHDRAWN'],
  APPLIED: ['ASSESSMENT', 'INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN'],
  ASSESSMENT: ['INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN'],
  INTERVIEW: ['OFFER', 'REJECTED', 'WITHDRAWN'],
  OFFER: ['WITHDRAWN'], REJECTED: [], WITHDRAWN: [],
}
const availableJobs = computed(() => jobs.value.filter(job => !apps.value.some(item => item.job_id === job.job_id)))
const columns = computed(() => order.map(status => ({ status, items: apps.value.filter(item => item.status === status) })))
const selectedInterviews = computed(() => interviews.value.filter(item => item.application_id === selected.value?.application_id))

async function load() {
  try {
    const [applicationResult, jobResult, interviewResult] = await Promise.all([
      api.get<{ items: Application[] }>('/api/applications'),
      api.get<{ items: Job[] }>('/api/jobs'),
      api.get<{ items: Interview[] }>('/api/interviews'),
    ])
    apps.value = applicationResult.items
    jobs.value = jobResult.items
    interviews.value = interviewResult.items
    if (selected.value) await select(apps.value.find(item => item.application_id === selected.value?.application_id) || null)
    error.value = ''
  } catch (reason) { error.value = (reason as Error).message }
}

async function select(item: Application | null) {
  if (!item) { selected.value = null; editingInterview.value = null; return }
  selected.value = (await api.get<{ application: Application }>(`/api/applications/${item.application_id}`)).application
  transitionForm.next_action = selected.value.next_action
  transitionForm.notes = selected.value.notes
  editingInterview.value = null
}

async function create() {
  if (!createForm.job_id) return
  const result = await api.post<{ application: Application }>('/api/applications', { ...createForm, command_id: commandId('create') })
  Object.assign(createForm, { job_id: '', status: 'PLANNED', next_action: '', notes: '' })
  await load()
  await select(result.application)
}

async function transition(status: string) {
  if (!selected.value) return
  const result = await api.post<{ application: Application }>(`/api/applications/${selected.value.application_id}/transitions`, {
    status, next_action: transitionForm.next_action, notes: transitionForm.notes,
    version: selected.value.version, command_id: commandId('status'),
  })
  await load()
  await select(result.application)
}

async function addInterview() {
  if (!selected.value) return
  await api.post(`/api/applications/${selected.value.application_id}/interviews`, interviewForm)
  Object.assign(interviewForm, { title: '技术面试', round_type: 'TECHNICAL', status: 'SCHEDULED', scheduled_at: '', notes: '' })
  await load()
}

function startInterviewEdit(item: Interview) {
  editingInterview.value = item
  Object.assign(interviewEdit, {
    title: item.title, round_type: item.round_type, status: item.status,
    scheduled_at: toTimeInput(item.scheduled_at), notes: item.notes, result: item.result,
  })
}

async function saveInterview() {
  const item = editingInterview.value
  if (!item) return
  await api.patch(`/api/interviews/${item.round_id}`, { ...interviewEdit, version: item.version })
  editingInterview.value = null
  await load()
}

async function changeInterviewStatus(item: Interview, status: 'COMPLETED' | 'CANCELLED') {
  await api.patch(`/api/interviews/${item.round_id}`, { version: item.version, status })
  if (editingInterview.value?.round_id === item.round_id) editingInterview.value = null
  await load()
}

function jobFor(item: Application) { return item.job || { company_name: '', title: '', location: '' } }
onMounted(load)
</script>

<template>
  <header class="page-header"><div><span class="eyebrow">PIPELINE</span><h1>投递追踪</h1><p>状态迁移写入不可跳号的事件时间线。</p></div><button class="secondary" @click="load">刷新</button></header>
  <p v-if="error" class="error">{{ error }}</p>
  <form class="panel quick-application" @submit.prevent="create"><select v-model="createForm.job_id" required><option value="">选择尚未建投递的岗位</option><option v-for="job in availableJobs" :key="job.job_id" :value="job.job_id">{{ job.company_name }} · {{ job.title }}</option></select><select v-model="createForm.status"><option>PLANNED</option><option>APPLIED</option></select><input v-model="createForm.next_action" placeholder="下一步动作" /><button class="primary">建立投递</button></form>

  <section class="kanban"><div v-for="column in columns" :key="column.status" class="kanban-column"><div class="kanban-head"><StatusBadge :value="column.status" /><span>{{ column.items.length }}</span></div><button v-for="item in column.items" :key="item.application_id" class="application-card" :class="{ selected: selected?.application_id === item.application_id }" @click="select(item)"><strong>{{ jobFor(item).company_name }}</strong><span>{{ jobFor(item).title }}</span><small>{{ item.next_action || '未设置下一步' }}</small></button></div></section>

  <section v-if="selected" class="panel application-detail">
    <div class="panel-title"><div><h2>{{ selected.job.company_name }} · {{ selected.job.title }}</h2><p>记录版本 v{{ selected.version }}</p></div><StatusBadge :value="selected.status" /></div>
    <div class="content-grid detail-split">
      <div>
        <h3>推进状态</h3><label>下一步动作<input v-model="transitionForm.next_action" /></label><label>记录<textarea v-model="transitionForm.notes" rows="4"></textarea></label>
        <div class="transition-buttons"><button v-for="target in allowed[selected.status]" :key="target" :class="target === 'REJECTED' || target === 'WITHDRAWN' ? 'danger' : 'primary'" @click="transition(target)">转为 {{ target }}</button></div>
        <h3>事件时间线</h3><div v-for="event in selected.events" :key="event.event_id" class="event-row"><span>{{ event.sequence }}</span><div><strong>{{ event.message }}</strong><small>{{ formatTime(event.created_at) }} · {{ event.from_status || 'START' }} → {{ event.to_status }}</small></div></div>
      </div>
      <div>
        <h3>新增面试轮次</h3>
        <form class="stack" @submit.prevent="addInterview"><input v-model="interviewForm.title" required /><div class="inline-fields"><select v-model="interviewForm.round_type"><option>ASSESSMENT</option><option>TECHNICAL</option><option>HR</option><option>MANAGER</option><option>OTHER</option></select><input v-model="interviewForm.scheduled_at" type="datetime-local" /></div><textarea v-model="interviewForm.notes" rows="3" placeholder="准备重点"></textarea><button class="secondary">添加轮次</button></form>
        <h3>已有轮次</h3>
        <EmptyState v-if="!selectedInterviews.length" title="暂无面试轮次" />
        <div v-for="item in selectedInterviews" :key="item.round_id" class="interview-row">
          <div><strong>第 {{ item.round_no }} 轮 · {{ item.title }}</strong><small>{{ formatTime(item.scheduled_at) }} · {{ item.result || '暂无结果' }}</small></div><StatusBadge :value="item.status" />
          <div class="row-actions"><button class="mini" @click="startInterviewEdit(item)">编辑</button><button v-if="item.status !== 'COMPLETED' && item.status !== 'CANCELLED'" class="mini" @click="changeInterviewStatus(item, 'COMPLETED')">完成</button><button v-if="item.status !== 'CANCELLED' && item.status !== 'COMPLETED'" class="mini danger-text" @click="changeInterviewStatus(item, 'CANCELLED')">取消</button></div>
        </div>
        <form v-if="editingInterview" class="inline-editor" @submit.prevent="saveInterview">
          <div class="panel-title"><h3>编辑面试轮次</h3><button type="button" class="ghost-dark" @click="editingInterview = null">关闭</button></div>
          <div class="form-grid"><label>标题<input v-model="interviewEdit.title" required /></label><label>时间<input v-model="interviewEdit.scheduled_at" type="datetime-local" /></label><label>类型<select v-model="interviewEdit.round_type"><option>ASSESSMENT</option><option>TECHNICAL</option><option>HR</option><option>MANAGER</option><option>OTHER</option></select></label><label>状态<select v-model="interviewEdit.status"><option>PLANNED</option><option>SCHEDULED</option><option>COMPLETED</option><option>CANCELLED</option></select></label><label class="wide">结果<input v-model="interviewEdit.result" placeholder="通过 / 未通过 / 待反馈或具体记录" /></label><label class="wide">备注<textarea v-model="interviewEdit.notes" rows="3"></textarea></label></div>
          <div class="form-actions"><button type="button" class="danger" @click="interviewEdit.status = 'CANCELLED'; saveInterview()">取消轮次</button><button type="button" class="secondary" @click="interviewEdit.status = 'COMPLETED'">标记完成并继续填写</button><button class="primary">保存修改</button></div>
        </form>
      </div>
    </div>
  </section>
</template>
