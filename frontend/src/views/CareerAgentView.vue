<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, formatTime } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import type { AgentCapabilities, AgentTrace, Application, Interview, Job, PendingAction, Task } from '../types'

type Message = { role: 'user' | 'assistant'; content: string }

const capabilities = ref<AgentCapabilities | null>(null)
const applications = ref<Application[]>([])
const jobs = ref<Job[]>([])
const interviews = ref<Interview[]>([])
const tasks = ref<Task[]>([])
const pending = ref<PendingAction[]>([])
const messages = ref<Message[]>([{ role: 'assistant', content: '我会先查询 OfferFlow 的实时数据，再回答岗位、投递和待办问题。涉及投递状态修改时，我只会生成确认卡片。' }])
const input = ref('')
const sending = ref(false)
const error = ref('')
const trace = ref<AgentTrace | null>(null)
const currentJobId = ref('')
const currentApplicationId = ref('')
const currentInterviewId = ref('')
const currentTaskId = ref('')
const chatId = ref(localStorage.getItem('offerflow-agent-chat-id') || `chat:${crypto.randomUUID()}`)
localStorage.setItem('offerflow-agent-chat-id', chatId.value)

const activePending = computed(() => pending.value.filter(item => item.status === 'PENDING'))
const toolsUsed = computed(() => trace.value?.events.filter(item => item.event_type === 'TOOL_END') || [])

async function load() {
  try {
    const [capability, jobData, applicationData, interviewData, taskData, actionData] = await Promise.all([
      api.get<AgentCapabilities>('/api/agent/capabilities'),
      api.get<{ items: Job[] }>('/api/jobs'),
      api.get<{ items: Application[] }>('/api/applications'),
      api.get<{ items: Interview[] }>('/api/interviews'),
      api.get<{ items: Task[] }>('/api/tasks'),
      api.get<{ items: PendingAction[] }>('/api/pending-actions'),
    ])
    capabilities.value = capability
    jobs.value = jobData.items; applications.value = applicationData.items
    interviews.value = interviewData.items; tasks.value = taskData.items; pending.value = actionData.items
    error.value = ''
  } catch (reason) { error.value = (reason as Error).message }
}

async function send() {
  const message = input.value.trim()
  if (!message || sending.value) return
  const history = messages.value.slice(-12)
  messages.value.push({ role: 'user', content: message }, { role: 'assistant', content: '' })
  const assistantIndex = messages.value.length - 1
  input.value = ''; sending.value = true; error.value = ''; trace.value = null
  try {
    await api.stream('/api/agent/chat/stream', {
      chat_id: chatId.value, message, history,
      current_job_id: currentJobId.value, current_application_id: currentApplicationId.value,
      current_interview_id: currentInterviewId.value, current_task_id: currentTaskId.value,
    }, event => {
      if (event.type === 'delta') messages.value[assistantIndex].content += String(event.text || '')
      if (event.type === 'pending_action') pending.value.unshift(event.action as PendingAction)
      if (event.type === 'complete') trace.value = event.trace as AgentTrace
    })
    await load()
  } catch (reason) {
    error.value = (reason as Error).message
    if (!messages.value[assistantIndex].content) messages.value.splice(assistantIndex, 1)
  } finally { sending.value = false }
}

async function confirm(action: PendingAction) {
  try {
    const response = await api.post<{ result: { to_status: string }; trace: AgentTrace }>(`/api/pending-actions/${action.action_id}/confirm`)
    messages.value.push({ role: 'assistant', content: `已按你的确认完成投递状态更新：${response.result.to_status}。` })
    trace.value = response.trace
    await load()
  } catch (reason) { error.value = (reason as Error).message }
}

async function cancel(action: PendingAction) {
  try { await api.post(`/api/pending-actions/${action.action_id}/cancel`); await load() }
  catch (reason) { error.value = (reason as Error).message }
}

function newChat() {
  chatId.value = `chat:${crypto.randomUUID()}`
  localStorage.setItem('offerflow-agent-chat-id', chatId.value)
  messages.value = [{ role: 'assistant', content: '新对话已开始。你可以问我未投递岗位、投递进度、近期待办或技能缺口。' }]
  trace.value = null
}

onMounted(load)
</script>

<template>
  <header class="page-header"><div><span class="eyebrow">CAREER AGENT · PHASE 4</span><h1>求职 Agent</h1><p>十个受控工具连接实时业务数据；任何投递写入都需要你的确认。</p></div><button class="secondary" @click="newChat">新对话</button></header>
  <p v-if="error" class="error">{{ error }}</p>
  <div v-if="capabilities" class="capability-bar"><strong :class="capabilities.available ? 'available' : 'danger-text'">{{ capabilities.available ? 'Qwen Agent 可用' : '未配置可用模型密钥' }}</strong><span>{{ capabilities.model }} · {{ capabilities.tool_count }} tools · {{ capabilities.trace_policy }}</span></div>

  <section class="agent-layout">
    <div class="agent-main panel">
      <div class="agent-context">
        <label>当前岗位<select v-model="currentJobId"><option value="">不指定</option><option v-for="item in jobs" :key="item.job_id" :value="item.job_id">{{ item.company_name }} · {{ item.title }}</option></select></label>
        <label>当前投递<select v-model="currentApplicationId"><option value="">不指定</option><option v-for="item in applications" :key="item.application_id" :value="item.application_id">{{ item.job.company_name }} · {{ item.status }}</option></select></label>
        <label>当前面试<select v-model="currentInterviewId"><option value="">不指定</option><option v-for="item in interviews" :key="item.round_id" :value="item.round_id">{{ item.title }}</option></select></label>
        <label>当前待办<select v-model="currentTaskId"><option value="">不指定</option><option v-for="item in tasks" :key="item.task_id" :value="item.task_id">{{ item.title }}</option></select></label>
      </div>
      <div class="chat-window">
        <article v-for="(message, index) in messages" :key="index" :class="['chat-message', message.role]"><small>{{ message.role === 'user' ? '你' : 'Career Agent' }}</small><p>{{ message.content || '正在查询实时数据…' }}</p></article>
      </div>
      <form class="chat-composer" @submit.prevent="send"><textarea v-model="input" rows="3" placeholder="例如：列出收藏但还没投递的岗位；或把某条投递提议更新为面试阶段" @keydown.ctrl.enter.prevent="send"></textarea><div><small>Ctrl + Enter 发送 · 对话全文不会写入 Trace</small><button class="primary" :disabled="sending || !capabilities?.available">{{ sending ? '处理中…' : '发送' }}</button></div></form>
    </div>

    <aside class="agent-side stack">
      <section class="panel"><div class="panel-title"><div><h2>待确认动作</h2><p>不点击确认，Application 不会变化。</p></div><span>{{ activePending.length }}</span></div><p v-if="!activePending.length" class="muted">当前没有待确认动作。</p><article v-for="action in activePending" :key="action.action_id" class="confirmation-card"><div><StatusBadge :value="action.payload.target_status" /><small>{{ formatTime(action.expires_at) }} 过期</small></div><strong>{{ action.payload.application_id }}</strong><p>目标状态：{{ action.payload.target_status }}<br />下一步：{{ action.payload.next_action || '未填写' }}</p><div><button class="danger" @click="cancel(action)">取消</button><button class="primary" @click="confirm(action)">确认并执行</button></div></article></section>
      <section class="panel"><div class="panel-title"><div><h2>Trace 摘要</h2><p>仅记录 allowlist 元数据，不保存消息、简历或完整 JD。</p></div></div><p v-if="!trace" class="muted">完成一次请求后显示。</p><template v-else><code>{{ trace.trace_id }}</code><div class="trace-meta"><span>{{ trace.status }}</span><span>{{ trace.total_ms }} ms</span><span>{{ trace.input_tokens + trace.output_tokens }} tokens</span></div><div v-for="item in toolsUsed" :key="`${item.sequence}-${item.tool_name}`" class="trace-row"><strong>{{ item.tool_name }}</strong><span>{{ item.risk }} · {{ item.status }} · {{ item.duration_ms }} ms</span></div></template></section>
    </aside>
  </section>
</template>
