<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, formatTime } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import { labelFor } from '../uiLabels'
import type { AgentCapabilities, AgentMemory, Application, ChatMessage, ChatThread, Interview, Job, PendingAction, Task } from '../types'

type Message = { role: 'user' | 'assistant'; content: string }
const capabilities = ref<AgentCapabilities | null>(null)
const threads = ref<ChatThread[]>([])
const messages = ref<Message[]>([])
const applications = ref<Application[]>([])
const jobs = ref<Job[]>([])
const interviews = ref<Interview[]>([])
const tasks = ref<Task[]>([])
const pending = ref<PendingAction[]>([])
const input = ref('')
const sending = ref(false)
const error = ref('')
const currentJobId = ref('')
const currentApplicationId = ref('')
const currentInterviewId = ref('')
const currentTaskId = ref('')
const chatId = ref('')
const activePending = computed(() => pending.value.filter(item => item.status === 'PENDING' && item.chat_id === chatId.value))

async function loadThreads() {
  threads.value = (await api.get<{ items: ChatThread[] }>('/api/chat-threads')).items
}

async function loadOfficial() {
  const [capability, jobData, applicationData, interviewData, taskData, actionData] = await Promise.all([
    api.get<AgentCapabilities>('/api/agent/capabilities'), api.get<{ items: Job[] }>('/api/jobs'),
    api.get<{ items: Application[] }>('/api/applications'), api.get<{ items: Interview[] }>('/api/interviews'),
    api.get<{ items: Task[] }>('/api/tasks'), api.get<{ items: PendingAction[] }>('/api/pending-actions'),
  ])
  capabilities.value = capability; jobs.value = jobData.items; applications.value = applicationData.items
  interviews.value = interviewData.items; tasks.value = taskData.items; pending.value = actionData.items
}

async function restoreMemory() {
  if (!chatId.value) return
  const memory = (await api.get<{ memory: AgentMemory | null }>(`/api/agent/memory/${encodeURIComponent(chatId.value)}`)).memory
  currentJobId.value = memory && jobs.value.some(item => item.job_id === memory.current_job_id && item.effective_status !== 'ARCHIVED') ? memory.current_job_id : ''
  currentApplicationId.value = memory && applications.value.some(item => item.application_id === memory.current_application_id) ? memory.current_application_id : ''
  currentInterviewId.value = memory && interviews.value.some(item => item.round_id === memory.current_interview_id) ? memory.current_interview_id : ''
  currentTaskId.value = memory && tasks.value.some(item => item.task_id === memory.current_task_id) ? memory.current_task_id : ''
}

async function openChat(id: string) {
  try {
    const result = await api.get<{ thread: ChatThread; messages: ChatMessage[] }>(`/api/chat-threads/${encodeURIComponent(id)}`)
    chatId.value = result.thread.chat_id; localStorage.setItem('offerflow-agent-chat-id', chatId.value)
    messages.value = result.messages.map(item => ({ role: item.role === 'USER' ? 'user' : 'assistant', content: item.content }))
    await loadOfficial(); await restoreMemory(); error.value = ''
  } catch (reason) { error.value = (reason as Error).message }
}

async function newChat() {
  try {
    const thread = (await api.post<{ thread: ChatThread }>('/api/chat-threads', {})).thread
    await loadThreads(); await openChat(thread.chat_id)
  } catch (reason) { error.value = (reason as Error).message }
}

async function renameThread(item: ChatThread) {
  const title = window.prompt('新的对话名称', item.title)?.trim()
  if (!title) return
  await api.patch(`/api/chat-threads/${encodeURIComponent(item.chat_id)}`, { title }); await loadThreads()
}

async function deleteThread(item: ChatThread) {
  if (!window.confirm(`删除对话“${item.title}”？`)) return
  await api.delete(`/api/chat-threads/${encodeURIComponent(item.chat_id)}`); await loadThreads()
  if (chatId.value === item.chat_id) {
    if (threads.value.length) await openChat(threads.value[0].chat_id); else await newChat()
  }
}

async function send() {
  const message = input.value.trim()
  if (!message || sending.value || !chatId.value) return
  messages.value.push({ role: 'user', content: message }, { role: 'assistant', content: '' })
  const assistantIndex = messages.value.length - 1
  input.value = ''; sending.value = true; error.value = ''
  try {
    await api.stream('/api/agent/chat/stream', {
      chat_id: chatId.value, message,
      current_job_id: currentJobId.value, current_application_id: currentApplicationId.value,
      current_interview_id: currentInterviewId.value, current_task_id: currentTaskId.value,
    }, event => {
      if (event.type === 'delta') messages.value[assistantIndex].content += String(event.text || '')
      if (event.type === 'pending_action') pending.value.unshift(event.action as PendingAction)
    })
    await loadThreads(); await loadOfficial(); await restoreMemory()
  } catch (reason) {
    error.value = (reason as Error).message
    if (!messages.value[assistantIndex].content) messages.value.splice(assistantIndex, 1)
  } finally { sending.value = false }
}

async function confirm(action: PendingAction) {
  try {
    const response = await api.post<{ result: { action_type: string; to_status?: string; task_id?: string } }>(`/api/pending-actions/${action.action_id}/confirm`)
    const text = response.result.action_type === 'TASK_CREATE'
      ? '待办已按你的确认创建。'
      : response.result.action_type === 'INTERVIEW_PROGRESSION'
        ? '已完成当前轮次，并创建下一轮面试和准备待办。'
        : `投递进度已更新为“${labelFor(response.result.to_status || '')}”。`
    messages.value.push({ role: 'assistant', content: text }); await loadOfficial()
  } catch (reason) { error.value = (reason as Error).message }
}
async function cancel(action: PendingAction) {
  try { await api.post(`/api/pending-actions/${action.action_id}/cancel`); await loadOfficial() }
  catch (reason) { error.value = (reason as Error).message }
}

onMounted(async () => {
  try {
    await Promise.all([loadThreads(), loadOfficial()])
    const remembered = localStorage.getItem('offerflow-agent-chat-id') || ''
    const target = threads.value.find(item => item.chat_id === remembered) || threads.value[0]
    if (target) await openChat(target.chat_id); else await newChat()
  } catch (reason) { error.value = (reason as Error).message }
})
</script>

<template>
  <header class="page-header"><div><h1>求职 Agent</h1><p>帮你分析 JD、优化简历、查询投递进度和管理待办。</p></div><button class="primary" @click="newChat">新对话</button></header>
  <p v-if="error" class="error">{{ error }}</p>
  <section class="agent-workspace">
    <aside class="panel chat-history"><div class="panel-title"><h2>最近对话</h2><span>{{ threads.length }}</span></div><p v-if="!threads.length" class="muted">还没有历史对话。</p><article v-for="item in threads" :key="item.chat_id" :class="{ active: item.chat_id === chatId }"><button class="thread-open" @click="openChat(item.chat_id)"><strong>{{ item.title }}</strong><small>{{ formatTime(item.updated_at) }}</small></button><div class="thread-actions"><button @click="renameThread(item)">重命名</button><button class="danger-text" @click="deleteThread(item)">删除</button></div></article></aside>
    <div class="agent-main panel">
      <details class="context-details"><summary>指定上下文（可选）</summary><div class="agent-context"><label>岗位<select v-model="currentJobId"><option value="">自动判断</option><option v-for="item in jobs" :key="item.job_id" :value="item.job_id">{{ item.company_name }} · {{ item.title }}</option></select></label><label>投递<select v-model="currentApplicationId"><option value="">自动判断</option><option v-for="item in applications" :key="item.application_id" :value="item.application_id">{{ item.job.company_name }} · {{ labelFor(item.status) }}</option></select></label><label>面试<select v-model="currentInterviewId"><option value="">自动判断</option><option v-for="item in interviews" :key="item.round_id" :value="item.round_id">{{ item.title }}</option></select></label><label>待办<select v-model="currentTaskId"><option value="">自动判断</option><option v-for="item in tasks" :key="item.task_id" :value="item.task_id">{{ item.title }}</option></select></label></div></details>
      <div class="chat-window"><div v-if="!messages.length" class="agent-welcome"><strong>今天想处理哪件求职事项？</strong><span>可以问岗位与简历差异、投递进度，也可以让我提议创建待办。</span></div><article v-for="(message, index) in messages" :key="index" :class="['chat-message', message.role]"><small>{{ message.role === 'user' ? '你' : '求职 Agent' }}</small><p>{{ message.content || '正在处理…' }}</p></article></div>
      <form class="chat-composer" @submit.prevent="send"><textarea v-model="input" rows="3" placeholder="例如：阿里这个 JD 和我的简历差在哪？" @keydown.ctrl.enter.prevent="send"></textarea><div><small>Ctrl + Enter 发送</small><button class="primary" :disabled="sending || !capabilities?.available">{{ sending ? '处理中…' : '发送' }}</button></div></form>
    </div>
    <aside class="panel confirmation-panel"><div class="panel-title"><div><h2>待你确认</h2><p>不点击确认，业务数据不会改变。</p></div><span>{{ activePending.length }}</span></div><p v-if="!activePending.length" class="muted">当前没有待确认动作。</p><article v-for="action in activePending" :key="action.action_id" class="confirmation-card"><div><StatusBadge :value="action.action_type" /><small>{{ formatTime(action.expires_at) }} 过期</small></div><template v-if="action.action_type === 'TASK_CREATE'"><strong>将创建待办：{{ action.payload.title }}</strong><p>类型：{{ labelFor(action.payload.task_type || '') }}<br />截止：{{ formatTime(action.payload.due_at || '') }}<br />优先级：{{ labelFor(action.payload.priority || '') }}</p></template><template v-else-if="action.action_type === 'INTERVIEW_PROGRESSION'"><strong>安排下一轮面试</strong><p>{{ action.payload.next_round_title }} · {{ formatTime(action.payload.next_round_scheduled_at || '') }}<br />准备待办：{{ action.payload.task_title }} · {{ formatTime(action.payload.task_due_at || '') }}</p></template><template v-else><strong>更新投递进度</strong><p>目标阶段：{{ labelFor(action.payload.target_status || '') }}</p></template><div><button class="danger" @click="cancel(action)">取消</button><button class="primary" @click="confirm(action)">确认并执行</button></div></article></aside>
  </section>
</template>
