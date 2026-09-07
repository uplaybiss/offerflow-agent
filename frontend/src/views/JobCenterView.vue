<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { Job, JobComparison, MatchCoverage, MatchResult, SourceRefreshPreview } from '../types'

type Capabilities = { llm_available: boolean; llm_model: string }
type SourceCapabilities = { contract_version: string; persistence: string; adapters: Array<{ key: string; display_name: string }> }
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
const sourceCapabilities = ref<SourceCapabilities | null>(null)
const parsing = ref(false)
const previewReady = ref(false)
const previewNotes = ref<string[]>([])
const previewConditions = ref<Record<string, unknown>>({})
const matchResult = ref<MatchResult | null>(null)
const matching = ref(false)
const explanation = ref('')
const explanationLoading = ref(false)
const sourceRefreshing = ref(false)
const compareIds = ref<string[]>([])
const comparison = ref<JobComparison | null>(null)
const comparing = ref(false)

const emptyForm = () => ({
  company_name: '', title: '', location: '', employment_type: '', recruitment_cycle: '', graduation_year: '',
  deadline: '', status: 'ACTIVE', description_text: '', required_skills: '', preferred_skills: '',
  source_type: 'JD_PASTE', source_name: '', source_url: '', external_job_id: '', company_career_url: '',
  adapter_key: '', source_company_id: '', is_favorite: true, source_metadata: {} as Record<string, unknown>,
})
const form = reactive(emptyForm())
const editForm = reactive(emptyForm())
const skillList = (text: string) => text.split(/[,，\n]/).map(item => item.trim()).filter(Boolean)
const query = computed(() => new URLSearchParams({ search: search.value, status: status.value, favorite_only: String(favoriteOnly.value) }).toString())
const comparisonRows = computed(() => {
  const items = comparison.value?.items || []
  return [
    { label: '地点', values: items.map(item => item.job.location || '—') },
    { label: '用工类型', values: items.map(item => item.job.employment_type || '—') },
    { label: '截止日期', values: items.map(item => item.job.deadline || '—') },
    { label: '岗位状态', values: items.map(item => item.job.effective_status) },
    { label: '匹配等级', values: items.map(item => item.match.grade) },
    { label: '必备覆盖', values: items.map(item => coverage(item.match.required_coverage)) },
    { label: '技能缺口', values: items.map(item => [...item.match.critical_gaps, ...item.match.other_gaps].join('、') || '无') },
    { label: '招聘来源', values: items.map(item => item.job.source_name || item.job.source_type) },
  ]
})

function sourceContract(metadata: Record<string, unknown>) {
  const value = metadata.source_contract
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function jobPayload(value: ReturnType<typeof emptyForm>) {
  const { adapter_key, source_company_id, ...fields } = value
  return {
    ...fields,
    required_skills: skillList(value.required_skills),
    preferred_skills: skillList(value.preferred_skills),
    source_metadata: {
      ...value.source_metadata,
      source_contract: { ...sourceContract(value.source_metadata), adapter_key: adapter_key.trim(), source_company_id: source_company_id.trim() },
    },
  }
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
    const result = await api.post<{ preview: JdPreview; persisted: boolean; requires_confirmation: boolean }>('/api/parsing/jd/preview', { text: form.description_text })
    const preview = result.preview
    for (const field of ['company_name', 'title', 'location', 'employment_type', 'recruitment_cycle', 'graduation_year', 'deadline'] as const) if (preview[field]) form[field] = preview[field]
    form.required_skills = preview.required_skills.join('，')
    form.preferred_skills = preview.preferred_skills.join('，')
    form.source_metadata = { phase2_parsed: { hard_conditions: preview.hard_conditions, extraction_notes: preview.extraction_notes, parser: preview.parser } }
    previewNotes.value = preview.extraction_notes; previewConditions.value = preview.hard_conditions; previewReady.value = true
  } catch (reason) { error.value = (reason as Error).message }
  finally { parsing.value = false }
}

async function create() {
  try {
    const result = await api.post<{ job: Job }>('/api/jobs', jobPayload(form))
    showForm.value = false; Object.assign(form, emptyForm())
    previewReady.value = false; previewNotes.value = []; previewConditions.value = {}
    await load(); await chooseJob(result.job)
  } catch (reason) { error.value = (reason as Error).message }
}

function startJobEdit(item: Job) {
  const contract = sourceContract(item.source_metadata)
  Object.assign(editForm, {
    ...item,
    required_skills: item.required_skills.join('，'), preferred_skills: item.preferred_skills.join('，'),
    adapter_key: String(contract.adapter_key || ''), source_company_id: String(contract.source_company_id || ''),
  })
  editingJob.value = true; notice.value = ''
}

async function saveJob() {
  if (!selected.value) return
  try {
    const result = await api.patch<{ job: Job }>(`/api/jobs/${selected.value.job_id}`, { version: selected.value.version, ...jobPayload(editForm) })
    selected.value = result.job; editingJob.value = false; notice.value = '岗位修改已保存'
    await load(); await loadMatch()
  } catch (reason) { error.value = (reason as Error).message }
}

async function chooseJob(item: Job) {
  selected.value = item; matchResult.value = null; explanation.value = ''; editingJob.value = false; notice.value = ''
  await loadMatch()
}

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

async function refreshSource() {
  if (!selected.value) return
  sourceRefreshing.value = true; notice.value = ''
  try {
    const result = await api.post<SourceRefreshPreview>(`/api/jobs/${selected.value.job_id}/source-refresh`)
    notice.value = result.message
    if (result.status === 'PREVIEW') {
      startJobEdit(selected.value)
      const update = result.update_preview
      for (const field of ['company_name', 'title', 'location', 'employment_type', 'recruitment_cycle', 'graduation_year', 'deadline', 'status', 'description_text', 'source_name', 'source_url', 'external_job_id', 'company_career_url'] as const) {
        const value = update[field]
        if (typeof value === 'string') editForm[field] = value
      }
      if (Array.isArray(update.required_skills)) editForm.required_skills = update.required_skills.join('，')
      if (Array.isArray(update.preferred_skills)) editForm.preferred_skills = update.preferred_skills.join('，')
      notice.value += '；更新内容已放入编辑表单，仍未保存。'
    }
  } catch (reason) { error.value = (reason as Error).message }
  finally { sourceRefreshing.value = false }
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
  try { comparison.value = (await api.post<{ comparison: JobComparison }>('/api/jobs/compare', { job_ids: compareIds.value })).comparison; error.value = '' }
  catch (reason) { error.value = (reason as Error).message }
  finally { comparing.value = false }
}

async function favorite(item: Job) { await api.patch(`/api/jobs/${item.job_id}`, { version: item.version, is_favorite: !item.is_favorite }); await load() }
async function archive(item: Job) { await api.patch(`/api/jobs/${item.job_id}`, { version: item.version, status: 'ARCHIVED' }); selected.value = null; matchResult.value = null; await load() }
function coverage(value: MatchCoverage) { return value.ratio === null ? 'N/A' : `${Math.round(value.ratio * 100)}%` }

onMounted(async () => {
  try {
    [capabilities.value, sourceCapabilities.value] = await Promise.all([
      api.get<Capabilities>('/api/parsing/capabilities'), api.get<SourceCapabilities>('/api/sources/capabilities'),
    ])
    await load()
  } catch (reason) { error.value = (reason as Error).message }
})
</script>

<template>
  <header class="page-header"><div><span class="eyebrow">JOB LIBRARY · PHASE 3</span><h1>岗位中心</h1><p>解析与来源刷新都先形成预览；岗位事实始终由你确认并可手工修正。</p></div><button class="primary" @click="showForm = !showForm">{{ showForm ? '收起' : '+ 新增岗位' }}</button></header>
  <p v-if="error" class="error">{{ error }}</p><p v-if="notice" class="success">{{ notice }}</p>

  <form v-if="showForm" class="panel form-panel create-panel" @submit.prevent="create">
    <div class="panel-title"><div><h2>新增岗位</h2><p>先粘贴原文，可选 AI 解析，校对后再保存。</p></div><span v-if="previewReady" class="preview-flag">未保存预览</span></div>
    <label class="wide">JD 原文<textarea v-model="form.description_text" rows="7" placeholder="粘贴真实招聘 JD"></textarea></label>
    <div class="resume-actions"><button type="button" class="secondary" :disabled="parsing || !capabilities?.llm_available" @click="parseJd">{{ parsing ? '解析中…' : '生成 AI 结构化预览' }}</button><span v-if="!capabilities?.llm_available">未配置模型时可直接手工填写</span><span v-else>{{ capabilities.llm_model }}</span></div>
    <div v-if="previewReady" class="preview-summary"><strong>待校对的解析信息</strong><span>硬条件：{{ JSON.stringify(previewConditions) }}</span><span v-if="previewNotes.length">提示：{{ previewNotes.join('；') }}</span></div>
    <div class="form-grid"><label>公司名称 *<input v-model="form.company_name" required /></label><label>岗位名称 *<input v-model="form.title" required /></label><label>地点<input v-model="form.location" /></label><label>截止日期<input v-model="form.deadline" type="date" /></label><label>用工类型<input v-model="form.employment_type" /></label><label>招聘批次<input v-model="form.recruitment_cycle" /></label><label>毕业年份<input v-model="form.graduation_year" /></label><label>来源类型<select v-model="form.source_type"><option>MANUAL</option><option>JD_PASTE</option><option>COMPANY_CAREER</option></select></label><label>来源名称<input v-model="form.source_name" /></label><label>外部岗位 ID<input v-model="form.external_job_id" /></label><label class="wide">来源链接<input v-model="form.source_url" type="url" /></label><label class="wide">企业 Career 链接<input v-model="form.company_career_url" type="url" /></label><label>适配器键（可选）<input v-model="form.adapter_key" placeholder="尚未安装可留空" /></label><label>企业来源 ID（可选）<input v-model="form.source_company_id" /></label><label class="wide">必备技能<input v-model="form.required_skills" /></label><label class="wide">加分技能<input v-model="form.preferred_skills" /></label></div>
    <div class="form-actions"><label class="inline-check"><input v-model="form.is_favorite" type="checkbox" /> 同时收藏</label><button class="primary">确认并保存岗位</button></div>
  </form>

  <section class="toolbar"><input v-model="search" placeholder="搜索公司、岗位、地点或 JD" @keyup.enter="load" /><select v-model="status" @change="load"><option value="">全部状态</option><option>ACTIVE</option><option>EXPIRED</option><option>CLOSED</option><option>ARCHIVED</option></select><label class="inline-check"><input v-model="favoriteOnly" type="checkbox" @change="load" /> 仅收藏</label><button class="secondary" @click="load">筛选</button><span class="compare-count">已选 {{ compareIds.length }}/4</span><button class="secondary" :disabled="compareIds.length < 2 || comparing" @click="compareJobs">{{ comparing ? '对比中…' : '对比岗位' }}</button></section>

  <section v-if="comparison" class="panel comparison-panel"><div class="panel-title"><div><h2>岗位对比</h2><p>{{ comparison.heuristic.version }} · {{ comparison.heuristic.disclaimer }}</p></div><button class="ghost-dark" @click="comparison = null">关闭</button></div><div class="comparison-scroll"><table><thead><tr><th>维度</th><th v-for="item in comparison.items" :key="item.job.job_id">{{ item.job.company_name }}<small>{{ item.job.title }}</small></th></tr></thead><tbody><tr v-for="row in comparisonRows" :key="row.label"><th>{{ row.label }}</th><td v-for="(value, index) in row.values" :key="index">{{ value }}</td></tr></tbody></table></div></section>

  <div class="content-grid job-layout">
    <section class="panel list-panel"><EmptyState v-if="!jobs.length" title="还没有岗位" note="点击右上角录入第一条真实岗位。" /><div v-for="item in jobs" :key="item.job_id" class="job-row" :class="{ selected: selected?.job_id === item.job_id }"><button class="star" :aria-label="item.is_favorite ? '取消收藏' : '收藏岗位'" @click.stop="favorite(item)">{{ item.is_favorite ? '★' : '☆' }}</button><label class="compare-check" title="加入岗位对比"><input type="checkbox" :checked="compareIds.includes(item.job_id)" @change="toggleCompare(item)" /></label><button class="job-select" @click="chooseJob(item)"><span class="job-copy"><strong>{{ item.company_name }} · {{ item.title }}</strong><span>{{ item.location || '地点待定' }} · 截止 {{ item.deadline || '未注明' }}</span><small>{{ item.source_name || item.source_type }}</small></span><StatusBadge :value="item.effective_status" /></button></div></section>
    <aside class="panel detail-panel"><EmptyState v-if="!selected" title="选择一条岗位" note="右侧将展示岗位事实、来源和确定性匹配。" /><template v-else>
      <div class="panel-title"><div><h2>{{ selected.title }}</h2><p>{{ selected.company_name }} · {{ selected.location || '地点待定' }} · v{{ selected.version }}</p></div><StatusBadge :value="selected.effective_status" /></div>
      <div class="tag-list"><span v-for="skill in selected.required_skills" :key="skill">必备 · {{ skill }}</span><span v-for="skill in selected.preferred_skills" :key="skill">加分 · {{ skill }}</span></div>
      <dl><dt>用工类型</dt><dd>{{ selected.employment_type || '—' }}</dd><dt>招聘批次</dt><dd>{{ selected.recruitment_cycle || '—' }}</dd><dt>毕业年份</dt><dd>{{ selected.graduation_year || '—' }}</dd><dt>来源</dt><dd>{{ selected.source_name || selected.source_type }}</dd><dt>外部岗位 ID</dt><dd>{{ selected.external_job_id || '—' }}</dd><dt>截止时间</dt><dd>{{ selected.deadline || '—' }}</dd></dl>
      <div class="source-actions"><button class="secondary" @click="startJobEdit(selected)">编辑岗位</button><button class="secondary" :disabled="sourceRefreshing" @click="refreshSource">{{ sourceRefreshing ? '检查中…' : '检查单条来源更新' }}</button><small>{{ sourceCapabilities?.contract_version }} · {{ sourceCapabilities?.adapters.length || 0 }} 个可用适配器</small></div>

      <form v-if="editingJob" class="inline-editor job-editor" @submit.prevent="saveJob"><div class="panel-title"><div><h3>编辑岗位</h3><p>来源预览不会自动保存，所有字段都可手工修正。</p></div><button type="button" class="ghost-dark" @click="editingJob = false">关闭</button></div><div class="form-grid"><label>公司名称<input v-model="editForm.company_name" required /></label><label>岗位名称<input v-model="editForm.title" required /></label><label>地点<input v-model="editForm.location" /></label><label>状态<select v-model="editForm.status"><option>ACTIVE</option><option>EXPIRED</option><option>CLOSED</option><option>ARCHIVED</option></select></label><label>用工类型<input v-model="editForm.employment_type" /></label><label>招聘批次<input v-model="editForm.recruitment_cycle" /></label><label>毕业年份<input v-model="editForm.graduation_year" /></label><label>截止日期<input v-model="editForm.deadline" type="date" /></label><label>来源类型<select v-model="editForm.source_type"><option>MANUAL</option><option>JD_PASTE</option><option>COMPANY_CAREER</option></select></label><label>来源名称<input v-model="editForm.source_name" /></label><label class="wide">来源链接<input v-model="editForm.source_url" /></label><label class="wide">企业 Career 链接<input v-model="editForm.company_career_url" /></label><label>外部岗位 ID<input v-model="editForm.external_job_id" /></label><label>适配器键<input v-model="editForm.adapter_key" /></label><label class="wide">必备技能<input v-model="editForm.required_skills" /></label><label class="wide">加分技能<input v-model="editForm.preferred_skills" /></label><label class="wide">JD 原文<textarea v-model="editForm.description_text" rows="7"></textarea></label></div><div class="form-actions"><button class="primary">确认保存修改</button></div></form>

      <section class="match-panel"><div class="panel-title"><div><h3>确定性匹配</h3><p v-if="matchResult">{{ matchResult.heuristic.version }} · {{ matchResult.heuristic.disclaimer }}</p></div><button class="secondary" :disabled="matching" @click="loadMatch">{{ matching ? '计算中…' : '重新计算' }}</button></div><template v-if="matchResult"><div class="match-overview"><StatusBadge :value="matchResult.grade" /><div><strong>{{ coverage(matchResult.required_coverage) }}</strong><small>必备技能覆盖 {{ matchResult.required_coverage.matched }}/{{ matchResult.required_coverage.total }}</small></div><div><strong>{{ coverage(matchResult.preferred_coverage) }}</strong><small>加分技能覆盖 {{ matchResult.preferred_coverage.matched }}/{{ matchResult.preferred_coverage.total }}</small></div></div><h4>硬条件</h4><div v-for="item in matchResult.hard_conditions" :key="item.name" class="condition-row"><StatusBadge :value="item.status" /><div><strong>{{ item.name }}</strong><small>{{ item.evidence }}</small></div></div><h4>技能证据</h4><div v-for="item in matchResult.required_coverage.evidence" :key="item.canonical_skill" class="skill-evidence"><span :class="item.matched ? 'hit' : 'gap'">{{ item.matched ? '命中' : '缺口' }}</span><div><strong>{{ item.job_skill }} → {{ item.canonical_skill }}</strong><small>{{ item.skill_category }} · {{ item.candidate_skill || '候选人无对应具体技能' }}</small></div></div><div class="gap-summary"><span>关键缺口：{{ matchResult.critical_gaps.join('、') || '无' }}</span><span>其他缺口：{{ matchResult.other_gaps.join('、') || '无' }}</span></div><button class="secondary" :disabled="!capabilities?.llm_available || explanationLoading" @click="explainMatch">{{ explanationLoading ? '解释生成中…' : '用 AI 解释上述确定性结果' }}</button><p v-if="explanation" class="explanation">{{ explanation }}</p></template></section>
      <h3>JD 原文</h3><pre>{{ selected.description_text || '未填写' }}</pre><div class="form-actions"><a v-if="selected.source_url" class="secondary" :href="selected.source_url" target="_blank">打开来源</a><button class="danger" @click="archive(selected)">归档岗位</button></div>
    </template></aside>
  </div>
</template>
