<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { JOB_STATUSES, labelFor } from '../uiLabels'
import type { Job, JobComparison, MatchCoverage, MatchResult } from '../types'

const emit = defineEmits<{ optimizeResume: [jobId: string] }>()
type Capabilities = { llm_available: boolean }
type JdPreview = {
  company_name: string; title: string; location: string; employment_type: string
  recruitment_cycle: string; graduation_year: string; deadline: string
  required_skills: string[]; preferred_skills: string[]
  hard_conditions: Record<string, unknown>; extraction_notes: string[]; parser: Record<string, string>
}

const jobs = ref<Job[]>([])
const selected = ref<Job | null>(null)
const showForm = ref(false)
const editingJob = ref(false)
const search = ref('')
const status = ref('')
const favoriteOnly = ref(false)
const error = ref('')
const notice = ref('')
const capabilities = ref<Capabilities | null>(null)
const parsing = ref(false)
const previewReady = ref(false)
const previewNotes = ref<string[]>([])
const previewConditions = ref<Record<string, unknown>>({})
const matchResult = ref<MatchResult | null>(null)
const matching = ref(false)
const explanation = ref('')
const explanationLoading = ref(false)
const compareIds = ref<string[]>([])
const comparison = ref<JobComparison | null>(null)
const comparing = ref(false)

const emptyForm = () => ({
  company_name: '', title: '', location: '', employment_type: '', recruitment_cycle: '', graduation_year: '',
  deadline: '', status: 'ACTIVE', description_text: '', required_skills: '', preferred_skills: '',
  source_type: 'JD_PASTE', source_name: '', source_url: '', external_job_id: '', company_career_url: '',
  is_favorite: true, source_metadata: {} as Record<string, unknown>,
})
const form = reactive(emptyForm())
const editForm = reactive(emptyForm())
const skillList = (text: string) => text.split(/[,，\n]/).map(item => item.trim()).filter(Boolean)
const query = computed(() => new URLSearchParams({ search: search.value, status: status.value, favorite_only: String(favoriteOnly.value) }).toString())
const conditionEntries = computed(() => Object.entries(previewConditions.value).filter(([, value]) => value !== null && value !== '' && !(Array.isArray(value) && !value.length)))
const comparisonRows = computed(() => {
  const items = comparison.value?.items || []
  return [
    { label: '地点', values: items.map(item => item.job.location || '—') },
    { label: '用工类型', values: items.map(item => item.job.employment_type || '—') },
    { label: '截止日期', values: items.map(item => item.job.deadline || '—') },
    { label: '岗位状态', values: items.map(item => labelFor(item.job.effective_status)) },
    { label: '匹配结论', values: items.map(item => labelFor(item.match.grade)) },
    { label: '必备技能覆盖', values: items.map(item => coverage(item.match.required_coverage)) },
    { label: '技能缺口', values: items.map(item => item.match.missing_required_skills.join('、') || '无') },
  ]
})

function jobPayload(value: ReturnType<typeof emptyForm>) {
  return { ...value, required_skills: skillList(value.required_skills), preferred_skills: skillList(value.preferred_skills) }
}

async function load() {
  try {
    jobs.value = (await api.get<{ items: Job[] }>(`/api/jobs?${query.value}`)).items
    if (selected.value) selected.value = jobs.value.find(item => item.job_id === selected.value?.job_id) || null
    compareIds.value = compareIds.value.filter(id => jobs.value.some(item => item.job_id === id))
    error.value = ''
  } catch (reason) { error.value = (reason as Error).message }
}

async function parseJd() {
  if (!form.description_text.trim()) { error.value = '请先粘贴 JD 原文'; return }
  parsing.value = true; error.value = ''
  try {
    const result = await api.post<{ preview: JdPreview }>('/api/parsing/jd/preview', { text: form.description_text })
    const preview = result.preview
    for (const field of ['company_name', 'title', 'location', 'employment_type', 'recruitment_cycle', 'graduation_year', 'deadline'] as const) if (preview[field]) form[field] = preview[field]
    form.required_skills = preview.required_skills.join('，'); form.preferred_skills = preview.preferred_skills.join('，')
    form.source_metadata = { phase2_parsed: { hard_conditions: preview.hard_conditions, extraction_notes: preview.extraction_notes } }
    previewNotes.value = preview.extraction_notes; previewConditions.value = preview.hard_conditions; previewReady.value = true
  } catch (reason) { error.value = (reason as Error).message }
  finally { parsing.value = false }
}

async function create() {
  try {
    const result = await api.post<{ job: Job }>('/api/jobs', jobPayload(form))
    showForm.value = false; Object.assign(form, emptyForm()); previewReady.value = false
    await load(); await chooseJob(result.job)
  } catch (reason) { error.value = (reason as Error).message }
}

function startJobEdit(item: Job) {
  Object.assign(editForm, { ...item, required_skills: item.required_skills.join('，'), preferred_skills: item.preferred_skills.join('，') })
  editingJob.value = true; notice.value = ''
}

async function saveJob() {
  if (!selected.value) return
  try {
    selected.value = (await api.patch<{ job: Job }>(`/api/jobs/${selected.value.job_id}`, { version: selected.value.version, ...jobPayload(editForm) })).job
    editingJob.value = false; notice.value = '岗位修改已保存'; await load(); await loadMatch()
  } catch (reason) { error.value = (reason as Error).message }
}

async function chooseJob(item: Job) { selected.value = item; explanation.value = ''; editingJob.value = false; await loadMatch() }
async function loadMatch() {
  if (!selected.value) return
  matching.value = true
  try { matchResult.value = (await api.get<{ match: MatchResult }>(`/api/jobs/${selected.value.job_id}/match`)).match }
  catch (reason) { error.value = (reason as Error).message }
  finally { matching.value = false }
}
async function explainMatch() {
  if (!selected.value) return
  explanationLoading.value = true
  try { explanation.value = (await api.post<{ explanation: string }>(`/api/jobs/${selected.value.job_id}/match/explanation`)).explanation }
  catch (reason) { error.value = (reason as Error).message }
  finally { explanationLoading.value = false }
}
function toggleCompare(item: Job) {
  if (compareIds.value.includes(item.job_id)) compareIds.value = compareIds.value.filter(id => id !== item.job_id)
  else if (compareIds.value.length < 4) compareIds.value = [...compareIds.value, item.job_id]
  else error.value = '一次最多对比 4 个岗位'
  comparison.value = null
}
async function compareJobs() {
  if (compareIds.value.length < 2) { error.value = '请先选择至少 2 个岗位'; return }
  comparing.value = true
  try { comparison.value = (await api.post<{ comparison: JobComparison }>('/api/jobs/compare', { job_ids: compareIds.value })).comparison }
  catch (reason) { error.value = (reason as Error).message }
  finally { comparing.value = false }
}
async function favorite(item: Job) { await api.patch(`/api/jobs/${item.job_id}`, { version: item.version, is_favorite: !item.is_favorite }); await load() }
async function archive(item: Job) { await api.patch(`/api/jobs/${item.job_id}`, { version: item.version, status: 'ARCHIVED' }); selected.value = null; await load() }
function coverage(value: MatchCoverage) { return value.ratio === null ? '未计算' : `${Math.round(value.ratio * 100)}%` }

onMounted(async () => { capabilities.value = await api.get<Capabilities>('/api/parsing/capabilities'); await load() })
</script>

<template>
  <header class="page-header"><div><h1>岗位中心</h1><p>保存你在招聘网站看到的真实岗位，再进行匹配、比较和简历优化。</p></div><button class="primary" @click="showForm = !showForm">{{ showForm ? '收起' : '新增岗位' }}</button></header>
  <p v-if="error" class="error">{{ error }}</p><p v-if="notice" class="success">{{ notice }}</p>

  <form v-if="showForm" class="panel form-panel create-panel" @submit.prevent="create">
    <div class="panel-title"><div><h2>新增岗位</h2><p>粘贴 JD 后可以先解析，所有结果都由你校对并保存。</p></div><span v-if="previewReady" class="preview-flag">尚未保存</span></div>
    <label class="wide">JD 原文<textarea v-model="form.description_text" rows="7" placeholder="粘贴真实招聘 JD"></textarea></label>
    <div class="resume-actions"><button type="button" class="secondary" :disabled="parsing || !capabilities?.llm_available" @click="parseJd">{{ parsing ? '解析中…' : 'AI 解析 JD' }}</button><span v-if="!capabilities?.llm_available">当前可手工填写</span></div>
    <div v-if="previewReady" class="preview-summary"><strong>请校对解析结果</strong><span v-for="([key, value]) in conditionEntries" :key="key">{{ key }}：{{ Array.isArray(value) ? value.join('、') : value }}</span><span v-if="previewNotes.length">提示：{{ previewNotes.join('；') }}</span></div>
    <div class="form-grid"><label>公司名称 *<input v-model="form.company_name" required /></label><label>岗位名称 *<input v-model="form.title" required /></label><label>地点<input v-model="form.location" /></label><label>截止日期<input v-model="form.deadline" type="date" /></label><label>用工类型<input v-model="form.employment_type" /></label><label>招聘批次<input v-model="form.recruitment_cycle" /></label><label>应届生届别<input v-model="form.graduation_year" /></label><label>来源名称<input v-model="form.source_name" placeholder="招聘官网 / Boss / 牛客" /></label><label class="wide">来源链接<input v-model="form.source_url" type="url" /></label><label class="wide">必备技能<input v-model="form.required_skills" /></label><label class="wide">加分技能<input v-model="form.preferred_skills" /></label></div>
    <div class="form-actions"><label class="inline-check"><input v-model="form.is_favorite" type="checkbox" /> 同时收藏</label><button class="primary">确认保存岗位</button></div>
  </form>

  <section class="toolbar job-toolbar"><label class="search-field">搜索<input v-model="search" placeholder="搜索公司、岗位、地点或 JD" @keyup.enter="load" /></label><label>状态<select v-model="status" @change="load"><option value="">全部状态</option><option v-for="item in JOB_STATUSES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label class="inline-check"><input v-model="favoriteOnly" type="checkbox" @change="load" /> 只看收藏</label><button class="secondary" @click="load">筛选</button><span class="compare-count">已选 {{ compareIds.length }}/4</span><button class="secondary" :disabled="compareIds.length < 2 || comparing" @click="compareJobs">{{ comparing ? '对比中…' : '对比岗位' }}</button></section>

  <section v-if="comparison" class="panel comparison-panel"><div class="panel-title"><h2>岗位对比</h2><button class="ghost-dark" @click="comparison = null">关闭</button></div><div class="comparison-scroll"><table><thead><tr><th>维度</th><th v-for="item in comparison.items" :key="item.job.job_id">{{ item.job.company_name }}<small>{{ item.job.title }}</small></th></tr></thead><tbody><tr v-for="row in comparisonRows" :key="row.label"><th>{{ row.label }}</th><td v-for="(value, index) in row.values" :key="index">{{ value }}</td></tr></tbody></table></div></section>

  <div class="content-grid job-layout">
    <section class="panel list-panel">
      <div v-if="!jobs.length" class="empty"><strong>还没有岗位。</strong><span>把你在招聘官网、Boss、牛客等地方看到的 JD 粘贴进来，我可以帮你解析和分析。</span><button class="primary" @click="showForm = true">新增岗位</button></div>
      <div v-for="item in jobs" :key="item.job_id" class="job-row" :class="{ selected: selected?.job_id === item.job_id }"><button class="star" :aria-label="item.is_favorite ? '取消收藏' : '收藏岗位'" @click.stop="favorite(item)">{{ item.is_favorite ? '★' : '☆' }}</button><label class="compare-check"><input type="checkbox" :checked="compareIds.includes(item.job_id)" @change="toggleCompare(item)" /></label><button class="job-select" @click="chooseJob(item)"><span class="job-copy"><strong>{{ item.company_name }} · {{ item.title }}</strong><span>{{ item.location || '地点待定' }} · 截止 {{ item.deadline || '未注明' }}</span></span><StatusBadge :value="item.effective_status" /></button></div>
    </section>
    <aside class="panel detail-panel"><EmptyState v-if="!selected" title="选择一条岗位" note="这里会展示岗位信息、匹配点和真实缺口。" /><template v-else>
      <div class="panel-title"><div><h2>{{ selected.title }}</h2><p>{{ selected.company_name }} · {{ selected.location || '地点待定' }}</p></div><StatusBadge :value="selected.effective_status" /></div>
      <div class="tag-list"><span v-for="skill in selected.required_skills" :key="skill">必备 · {{ skill }}</span><span v-for="skill in selected.preferred_skills" :key="skill">加分 · {{ skill }}</span></div>
      <dl><dt>用工类型</dt><dd>{{ selected.employment_type || '—' }}</dd><dt>招聘批次</dt><dd>{{ selected.recruitment_cycle || '—' }}</dd><dt>应届生届别</dt><dd>{{ selected.graduation_year || '—' }}</dd><dt>来源</dt><dd>{{ selected.source_name || '手工录入' }}</dd><dt>截止日期</dt><dd>{{ selected.deadline || '—' }}</dd></dl>
      <div class="source-actions"><button class="secondary" @click="startJobEdit(selected)">编辑岗位</button><button class="primary" @click="emit('optimizeResume', selected.job_id)">针对该岗位优化简历</button></div>
      <form v-if="editingJob" class="inline-editor job-editor" @submit.prevent="saveJob"><div class="panel-title"><h3>编辑岗位</h3><button type="button" class="ghost-dark" @click="editingJob = false">关闭</button></div><div class="form-grid"><label>公司名称<input v-model="editForm.company_name" required /></label><label>岗位名称<input v-model="editForm.title" required /></label><label>地点<input v-model="editForm.location" /></label><label>状态<select v-model="editForm.status"><option v-for="item in JOB_STATUSES" :key="item" :value="item">{{ labelFor(item) }}</option></select></label><label>用工类型<input v-model="editForm.employment_type" /></label><label>招聘批次<input v-model="editForm.recruitment_cycle" /></label><label>应届生届别<input v-model="editForm.graduation_year" /></label><label>截止日期<input v-model="editForm.deadline" type="date" /></label><label class="wide">来源链接<input v-model="editForm.source_url" /></label><label class="wide">必备技能<input v-model="editForm.required_skills" /></label><label class="wide">加分技能<input v-model="editForm.preferred_skills" /></label><label class="wide">JD 原文<textarea v-model="editForm.description_text" rows="7"></textarea></label></div><div class="form-actions"><button class="primary">保存修改</button></div></form>
      <section class="match-panel"><div class="panel-title"><div><h3>岗位匹配</h3><p>结果用于梳理事实，不代表录用概率。</p></div><button class="secondary" :disabled="matching" @click="loadMatch">{{ matching ? '计算中…' : '重新计算' }}</button></div><template v-if="matchResult"><div class="match-overview"><StatusBadge :value="matchResult.grade" /><div><strong>{{ coverage(matchResult.required_coverage) }}</strong><small>必备技能 {{ matchResult.required_coverage.matched }}/{{ matchResult.required_coverage.total }}</small></div><div><strong>{{ coverage(matchResult.preferred_coverage) }}</strong><small>加分技能 {{ matchResult.preferred_coverage.matched }}/{{ matchResult.preferred_coverage.total }}</small></div></div><h4>硬条件</h4><div v-for="item in matchResult.hard_conditions" :key="item.name" class="condition-row"><StatusBadge :value="item.status" /><div><strong>{{ item.name }}</strong><small>{{ item.evidence }}</small></div></div><h4>技能匹配</h4><div v-for="item in matchResult.required_coverage.evidence" :key="item.job_skill" class="skill-evidence"><span :class="item.matched ? 'hit' : 'gap'">{{ item.matched ? '已具备' : '缺口' }}</span><div><strong>{{ item.job_skill }}</strong><small>{{ item.candidate_skill || '个人技能中未找到对应项' }}</small></div></div><div class="gap-summary"><span>必备技能缺口：{{ matchResult.missing_required_skills.join('、') || '无' }}</span><span>加分技能缺口：{{ matchResult.missing_preferred_skills.join('、') || '无' }}</span></div><button class="secondary" :disabled="!capabilities?.llm_available || explanationLoading" @click="explainMatch">{{ explanationLoading ? '生成中…' : 'AI 解读匹配结果' }}</button><p v-if="explanation" class="explanation">{{ explanation }}</p></template></section>
      <h3>JD 原文</h3><pre>{{ selected.description_text || '未填写' }}</pre><div class="form-actions"><a v-if="selected.source_url" class="secondary" :href="selected.source_url" target="_blank">打开来源</a><button class="danger" @click="archive(selected)">归档岗位</button></div>
    </template></aside>
  </div>
</template>
