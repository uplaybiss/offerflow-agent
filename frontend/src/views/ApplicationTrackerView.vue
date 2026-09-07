<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, commandId, formatTime, toTimeInput } from '../api'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { APPLICATION_ORDER, INTERVIEW_STATUSES, INTERVIEW_TYPES, labelFor } from '../uiLabels'
import type { Application, Interview, Job } from '../types'

const apps = ref<Application[]>([])
const jobs = ref<Job[]>([])
const interviews = ref<Interview[]>([])
const transitions = ref<Record<string, string[]>>({})
const selected = ref<Application | null>(null)
const editingInterview = ref<Interview | null>(null)
const error = ref('')
const notice = ref('')
const createForm = reactive({ job_id: '', status: 'PLANNED', notes: '' })
const transitionNotes = ref('')
const interviewForm = reactive({ title: '技术面试', round_type: 'TECHNICAL', status: 'SCHEDULED', scheduled_at: '', notes: '' })
const interviewEdit = reactive({ title: '', round_type: 'TECHNICAL', status: 'SCHEDULED', scheduled_at: '', notes: '', result: '' })
const availableJobs = computed(() => jobs.value.filter(job => !apps.value.some(item => item.job_id === job.job_id) && job.effective_status !== 'ARCHIVED'))
const columns = computed(() => APPLICATION_ORDER.map(status => ({ status, items: apps.value.filter(item => item.status === status) })))
const selectedInterviews = computed(() => interviews.value.filter(item => item.application_id === selected.value?.application_id))
const nextStages = computed(() => selected.value ? transitions.value[selected.value.status] || [] : [])

async function load() {
  try {
    const [applicationResult, jobResult, interviewResult, transitionResult] = await Promise.all([
      api.get<{ items: Application[] }>('/api/applications'), api.get<{ items: Job[] }>('/api/jobs'),
      api.get<{ items: Interview[] }>('/api/interviews'), api.get<{ transitions: Record<string, string[]> }>('/api/applications/transitions/config'),
    ])
    apps.value = applicationResult.items; jobs.value = jobResult.items; interviews.value = interviewResult.items
    transitions.value = transitionResult.transitions
    if (selected.value) await select(apps.value.find(item => item.application_id === selected.value?.application_id) || null)
    error.value = ''
  } catch (reason) { error.value = (reason as Error).message }
}

async function select(item: Application | null) {
  if (!item) { selected.value = null; return }
  selected.value = (await api.get<{ application: Application }>(`/api/applications/${item.application_id}`)).application
  transitionNotes.value = selected.value.notes; editingInterview.value = null
}

async function create() {
  if (!createForm.job_id) return
  try {
    const result = await api.post<{ application: Application }>('/api/applications', { ...createForm, command_id: commandId('create') })
    Object.assign(createForm, { job_id: '', status: 'PLANNED', notes: '' }); notice.value = '投递记录已建立'
    await load(); await select(result.application)
  } catch (reason) { error.value = (reason as Error).message }
}

async function transition(status: string) {
  if (!selected.value) return
  try {
    const result = await api.post<{ application: Application }>(`/api/applications/${selected.value.application_id}/transitions`, {
      status, notes: transitionNotes.value, version: selected.value.version, command_id: commandId('status'),
    })
    notice.value = `进度已更新为“${labelFor(status)}”`; await load(); await select(result.application)
  } catch (reason) { error.value = (reason as Error).message }
}

async function addInterview() {
  if (!selected.value) return
  try {
    await api.post(`/api/applications/${selected.value.application_id}/interviews`, interviewForm)
    Object.assign(interviewForm, { title: '技术面试', round_type: 'TECHNICAL', status: 'SCHEDULED', scheduled_at: '', notes: '' })
    notice.value = '面试轮次已添加'; await load()
  } catch (reason) { error.value = (reason as Error).message }
}
function prepareNextRound() { interviewForm.title = `第 ${selectedInterviews.value.length + 1} 轮面试`; interviewForm.status = 'SCHEDULED' }
function startInterviewEdit(item: Interview) {
  editingInterview.value = item
  Object.assign(interviewEdit, { title: item.title, round_type: item.round_type, status: item.status, scheduled_at: toTimeInput(item.scheduled_at), notes: item.notes, result: item.result })
}
async function saveInterview() {
  if (!editingInterview.value) return
  await api.patch(`/api/interviews/${editingInterview.value.round_id}`, { ...interviewEdit, version: editingInterview.value.version })
  editingInterview.value = null; await load()
}
async function changeInterviewStatus(item: Interview, status: 'COMPLETED' | 'CANCELLED') {
  await api.patch(`/api/interviews/${item.round_id}`, { version: item.version, status }); await load()
}
function jobFor(item: Application) { return item.job || { company_name: '', title: '', location: '' } }
onMounted(load)
</script>

<template>
  <header class="page-header"><div><h1>投递进度</h1><p>记录每次真实投递，并按有效阶段推进笔试、面试和结果。</p></div><button class="secondary" @click="load">刷新</button></header>
  <p v-if="error" class="error">{{ error }}</p><p v-if="notice" class="success">{{ notice }}</p>
  <form class="panel application-create-form" @submit.prevent="create">
    <div class="panel-title"><div><h2>建立投递</h2><p>显示岗位中心中尚未建立投递记录的岗位。</p></div></div>
    <p v-if="!availableJobs.length" class="muted">目前没有可以建立投递的岗位，请先前往岗位中心添加岗位。</p>
    <div v-else class="form-grid"><label>岗位<select v-model="createForm.job_id" required><option value="">请选择岗位</option><option v-for="job in availableJobs" :key="job.job_id" :value="job.job_id">{{ job.company_name }} · {{ job.title }}</option></select></label><label>当前进度<select v-model="createForm.status"><option value="PLANNED">准备投递</option><option value="APPLIED">已投递</option></select></label><label class="wide">备注（可选）<textarea v-model="createForm.notes" rows="2"></textarea></label></div>
    <div v-if="availableJobs.length" class="form-actions"><button class="primary">建立投递</button></div>
  </form>

  <section class="kanban"><div v-for="column in columns" :key="column.status" class="kanban-column"><div class="kanban-head"><StatusBadge :value="column.status" /><span>{{ column.items.length }}</span></div><button v-for="item in column.items" :key="item.application_id" class="application-card" :class="{ selected: selected?.application_id === item.application_id }" @click="select(item)"><strong>{{ jobFor(item).company_name }}</strong><span>{{ jobFor(item).title }}</span><small>更新于 {{ formatTime(item.updated_at) }}</small></button></div></section>

  <section v-if="selected" class="panel application-detail">
    <div class="panel-title"><div><h2>{{ selected.job.company_name }} · {{ selected.job.title }}</h2><p>当前进度</p></div><StatusBadge :value="selected.status" /></div>
    <div class="content-grid detail-split">
      <div><h3>下一阶段</h3><label>备注<textarea v-model="transitionNotes" rows="4" placeholder="可记录本次进展"></textarea></label><div class="transition-buttons"><button v-for="target in nextStages" :key="target" :class="target === 'REJECTED' || target === 'WITHDRAWN' ? 'danger' : 'primary'" @click="transition(target)">{{ labelFor(target) }}</button><button v-if="selected.status === 'INTERVIEW'" class="secondary" @click="prepareNextRound">下一轮面试</button></div><p v-if="!nextStages.length" class="muted">当前状态没有后续阶段。</p>
        <h3>进度记录</h3><div v-for="event in selected.events" :key="event.event_id" class="event-row"><span>{{ event.sequence }}</span><div><strong>{{ event.message }}</strong><small>{{ formatTime(event.created_at) }} · {{ event.from_status ? labelFor(event.from_status) : '建立记录' }} → {{ labelFor(event.to_status) }}</small></div></div>
      </div>
      <div><h3>新增面试轮次</h3><form class="stack" @submit.prevent="addInterview"><input v-model="interviewForm.title" required /><div class="inline-fields"><select v-model="interviewForm.round_type"><option v-for="item in INTERVIEW_TYPES" :key="item" :value="item">{{ labelFor(item) }}</option></select><input v-model="interviewForm.scheduled_at" type="datetime-local" /></div><textarea v-model="interviewForm.notes" rows="3" placeholder="准备重点"></textarea><button class="secondary">添加轮次</button></form>
        <h3>已有轮次</h3><EmptyState v-if="!selectedInterviews.length" title="暂无面试轮次" /><div v-for="item in selectedInterviews" :key="item.round_id" class="interview-row"><div><strong>第 {{ item.round_no }} 轮 · {{ item.title }}</strong><small>{{ formatTime(item.scheduled_at) }} · {{ item.result || '暂无结果' }}</small></div><StatusBadge :value="item.status" /><div class="row-actions"><button class="mini" @click="startInterviewEdit(item)">编辑</button><button v-if="!['COMPLETED','CANCELLED'].includes(item.status)" class="mini" @click="changeInterviewStatus(item, 'COMPLETED')">完成</button><button v-if="!['COMPLETED','CANCELLED'].includes(item.status)" class="mini danger-text" @click="changeInterviewStatus(item, 'CANCELLED')">取消</button></div></div>
        <form v-if="editingInterview" class="inline-editor" @submit.prevent="saveInterview"><div class="panel-title"><h3>编辑面试轮次</h3><button type="button" class="ghost-dark" @click="editingInterview = null">关闭</button></div><div class="form-grid"><label>标题<input v-model="interviewEdit.title" required /></label><label>时间<input v-model="interviewEdit.scheduled_at" type="datetime-local" /></label><label>类型<select v-model="interviewEdit.round_type"><option v-for="item in INTERVIEW_TYPES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label>状态<select v-model="interviewEdit.status"><option v-for="item in INTERVIEW_STATUSES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label class="wide">结果<input v-model="interviewEdit.result" placeholder="通过 / 未通过 / 待反馈" /></label><label class="wide">备注<textarea v-model="interviewEdit.notes" rows="3"></textarea></label></div><div class="form-actions"><button class="primary">保存修改</button></div></form>
      </div>
    </div>
  </section>
</template>
