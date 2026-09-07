<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, formatTime } from '../api'
import EmptyState from '../components/EmptyState.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { labelFor } from '../uiLabels'
import type { Job, ResumeAnalysis, ResumeSuggestion, ResumeVersion } from '../types'

const props = defineProps<{ initialJobId?: string }>()
type Candidate = {
  candidate_id: string; version: number; current_resume_text: string; current_resume_parsed: Record<string, unknown>
  current_resume_filename: string; current_resume_sha256: string; resume_updated_at: string; skills: string[]
  full_name: string; email: string; phone: string; graduation_year: string; degree: string
  target_roles: string[]; preferred_cities: string[]; excluded_companies: string[]; preferences: Record<string, unknown>
}

const candidate = ref<Candidate | null>(null)
const jobs = ref<Job[]>([])
const versions = ref<ResumeVersion[]>([])
const selectedJobId = ref('')
const selectedVersion = ref<ResumeVersion | null>(null)
const analysis = ref<ResumeAnalysis | null>(null)
const draftText = ref('')
const versionTitle = ref('')
const baseEditing = ref(false)
const baseText = ref('')
const baseFilename = ref('')
const versionEditing = ref(false)
const versionEdit = reactive({ title: '', content_text: '', source_job_id: '' })
const loading = ref(false)
const error = ref('')
const notice = ref('')
const selectedJob = computed(() => jobs.value.find(item => item.job_id === selectedJobId.value) || null)

async function load() {
  const [candidateData, jobData, versionData] = await Promise.all([
    api.get<{ candidate: Candidate }>('/api/candidate'),
    api.get<{ items: Job[] }>('/api/jobs'),
    api.get<{ items: ResumeVersion[] }>('/api/resume-versions?include_archived=true'),
  ])
  candidate.value = candidateData.candidate; jobs.value = jobData.items; versions.value = versionData.items
  baseText.value = candidate.value.current_resume_text; baseFilename.value = candidate.value.current_resume_filename
  if (props.initialJobId && jobs.value.some(item => item.job_id === props.initialJobId)) selectedJobId.value = props.initialJobId
}

async function saveBase() {
  if (!candidate.value) return
  try {
    const current = candidate.value
    candidate.value = (await api.put<{ candidate: Candidate }>('/api/candidate', {
      version: current.version, full_name: current.full_name, email: current.email, phone: current.phone,
      graduation_year: current.graduation_year, degree: current.degree, target_roles: current.target_roles,
      preferred_cities: current.preferred_cities, excluded_companies: current.excluded_companies,
      preferences: current.preferences, skills: current.skills, current_resume_text: baseText.value,
      current_resume_parsed: current.current_resume_parsed, current_resume_filename: baseFilename.value,
    })).candidate
    baseEditing.value = false; notice.value = '基础简历已保存'
  } catch (reason) { error.value = (reason as Error).message }
}

async function tailor() {
  if (!selectedJobId.value) { error.value = '请先选择一个岗位'; return }
  loading.value = true; error.value = ''; notice.value = ''; analysis.value = null
  try {
    analysis.value = (await api.post<{ analysis: ResumeAnalysis }>('/api/resume-tailoring/analyze', { job_id: selectedJobId.value })).analysis
    draftText.value = candidate.value?.current_resume_text || ''
    versionTitle.value = `${analysis.value.job.company_name} · ${analysis.value.job.title}版`
  } catch (reason) { error.value = (reason as Error).message }
  finally { loading.value = false }
}

function applySuggestion(item: ResumeSuggestion) {
  if (!item.safe_to_apply) return
  if (item.original_text && draftText.value.includes(item.original_text)) draftText.value = draftText.value.replace(item.original_text, item.suggested_text)
  else if (item.suggested_text && !draftText.value.includes(item.suggested_text)) draftText.value += `\n${item.suggested_text}`
}

async function saveVersion() {
  if (!analysis.value || !versionTitle.value.trim() || !draftText.value.trim()) return
  try {
    const item = (await api.post<{ resume_version: ResumeVersion }>('/api/resume-versions', {
      source_job_id: selectedJobId.value, title: versionTitle.value, content_text: draftText.value,
      structured: {
        source: 'resume_tailoring_preview', job: analysis.value.job,
        suggestion_validation: analysis.value.suggestions.map(value => ({ section: value.section, status: value.validation_status })),
      },
      created_from: 'AI_TAILORED',
    })).resume_version
    versions.value.unshift(item); selectedVersion.value = item; analysis.value = null
    notice.value = `已保存“${item.title}”，基础简历未改变。`
  } catch (reason) { error.value = (reason as Error).message }
}

function viewVersion(item: ResumeVersion) { selectedVersion.value = item; versionEditing.value = false }
function startVersionEdit(item: ResumeVersion) {
  selectedVersion.value = item; versionEditing.value = true
  Object.assign(versionEdit, { title: item.title, content_text: item.content_text, source_job_id: item.source_job_id })
}
async function saveVersionEdit() {
  if (!selectedVersion.value) return
  try {
    selectedVersion.value = (await api.patch<{ resume_version: ResumeVersion }>(`/api/resume-versions/${selectedVersion.value.resume_version_id}`, {
      version: selectedVersion.value.version, ...versionEdit,
    })).resume_version
    versionEditing.value = false; await load(); notice.value = '简历版本修改已保存'
  } catch (reason) { error.value = (reason as Error).message }
}
async function copyText(item: ResumeVersion) {
  try { await navigator.clipboard.writeText(item.content_text); notice.value = `已复制“${item.title}”的文本` }
  catch { error.value = '浏览器未允许复制，请打开版本后手工复制' }
}
async function archive(item: ResumeVersion) {
  await api.patch(`/api/resume-versions/${item.resume_version_id}`, { version: item.version, archived: true })
  if (selectedVersion.value?.resume_version_id === item.resume_version_id) selectedVersion.value = null
  await load(); notice.value = '简历版本已归档'
}

watch(() => props.initialJobId, value => { if (value) selectedJobId.value = value })
onMounted(() => load().catch(reason => { error.value = (reason as Error).message }))
</script>

<template>
  <header class="page-header"><div><h1>简历中心</h1><p>维护基础简历，并根据不同 JD 创建针对性的求职版本。</p></div></header>
  <p v-if="notice" class="success">{{ notice }}</p><p v-if="error" class="error">{{ error }}</p>
  <section class="panel base-resume-card">
    <div class="panel-title"><div><h2>基础简历</h2><p>{{ candidate?.current_resume_filename || '尚未设置文件名' }} · 最后更新 {{ candidate?.resume_updated_at ? formatTime(candidate.resume_updated_at) : '尚未保存' }}</p></div><div class="row-actions"><button class="secondary" @click="baseEditing = !baseEditing">{{ baseEditing ? '收起' : '查看 / 编辑' }}</button></div></div>
    <div class="tag-list"><span v-for="skill in candidate?.skills" :key="skill">{{ skill }}</span><span v-if="!candidate?.skills.length">请先在个人中心填写技能</span></div>
    <form v-if="baseEditing" class="inline-editor" @submit.prevent="saveBase"><label>文件名<input v-model="baseFilename" /></label><label>基础简历文本<textarea v-model="baseText" rows="16"></textarea></label><div class="form-actions"><button class="primary">保存基础简历</button></div></form>
  </section>

  <section class="panel tailor-start">
    <div class="panel-title"><div><h2>针对岗位优化</h2><p>AI 只提出基于现有事实的建议；保存前由你逐条核对和编辑。</p></div></div>
    <div class="tailor-controls"><label>选择岗位<select v-model="selectedJobId"><option value="">请选择已保存岗位</option><option v-for="job in jobs" :key="job.job_id" :value="job.job_id">{{ job.company_name }} · {{ job.title }}</option></select></label><button class="primary" :disabled="loading || !selectedJobId || !candidate?.current_resume_text" @click="tailor">{{ loading ? '分析中…' : '针对该岗位优化简历' }}</button></div>
    <small v-if="!candidate?.current_resume_text" class="muted">请先在个人中心或本页保存基础简历。</small>
  </section>

  <section v-if="analysis" class="panel tailoring-result">
    <div class="panel-title"><div><h2>{{ analysis.job.company_name }} · {{ analysis.job.title }}</h2><p>{{ analysis.validation_disclosure }}</p></div><span class="preview-flag">预览，尚未保存</span></div>
    <div class="tailoring-summary"><article><h3>岗位核心要求</h3><div class="tag-list"><span v-for="item in analysis.core_requirements" :key="item">{{ item }}</span></div></article><article><h3>明确匹配</h3><div class="tag-list"><span v-for="item in analysis.matched" :key="item">{{ item }}</span><span v-if="!analysis.matched.length">暂无</span></div></article><article><h3>已有事实但不够突出</h3><div class="tag-list"><span v-for="item in analysis.underemphasized_facts" :key="item">{{ item }}</span><span v-if="!analysis.underemphasized_facts.length">暂无</span></div></article><article class="gap-card"><h3>真实缺口</h3><div class="tag-list"><span v-for="item in analysis.gaps" :key="item">{{ item }}</span><span v-if="!analysis.gaps.length">暂无明确技能缺口</span></div></article></div>
    <h3>建议调整</h3>
    <div class="recommendation-list"><article v-for="(item, index) in analysis.suggestions" :key="index" class="recommendation-card"><div><strong>{{ item.section }} · {{ item.change_type }}</strong><StatusBadge :value="item.validation_status" /></div><p><b>原文：</b>{{ item.original_text || '不涉及原句' }}</p><p><b>建议：</b>{{ item.suggested_text }}</p><p><b>理由：</b>{{ item.reason }}</p><small>事实依据：{{ item.evidence || '需要人工核对' }}<br />对应要求：{{ item.jd_requirement || '—' }}</small><p v-if="item.validation_reasons.length" class="danger-text">{{ item.validation_reasons.join('；') }}</p><button class="secondary" :disabled="!item.safe_to_apply" @click="applySuggestion(item)">{{ item.safe_to_apply ? '应用到草稿' : '不可应用' }}</button></article><EmptyState v-if="!analysis.suggestions.length" title="没有生成改写建议" note="你仍可根据匹配点和缺口手工编辑草稿。" /></div>
    <div class="version-compose"><label>新版本名称<input v-model="versionTitle" /></label><label>版本内容<textarea v-model="draftText" rows="20"></textarea></label><div class="form-actions"><small>点击保存只会创建新版本，不会覆盖基础简历。</small><button class="primary" @click="saveVersion">保存为新版本</button></div></div>
  </section>

  <section class="panel version-library">
    <div class="panel-title"><div><h2>岗位定制版本</h2><p>每个版本都是创建当时的独立快照。</p></div><span>{{ versions.filter(item => !item.archived).length }} 份</span></div>
    <EmptyState v-if="!versions.filter(item => !item.archived).length" title="还没有岗位定制简历" note="选择上方岗位并完成一次优化后保存。" />
    <div v-for="item in versions.filter(value => !value.archived)" :key="item.resume_version_id" class="version-row"><div><strong>{{ item.title }}</strong><small>关联岗位：{{ item.job?.company_name ? `${item.job.company_name} · ${item.job.title}` : '未关联' }} · 创建于 {{ formatTime(item.created_at) }}</small></div><div class="row-actions"><button class="mini" @click="viewVersion(item)">查看</button><button class="mini" @click="startVersionEdit(item)">编辑</button><button class="mini" @click="copyText(item)">复制</button><button class="mini danger-text" @click="archive(item)">归档</button></div></div>
  </section>

  <section v-if="selectedVersion" class="panel version-detail">
    <div class="panel-title"><div><h2>{{ selectedVersion.title }}</h2><p>{{ labelFor(selectedVersion.created_from) }} · 版本 {{ selectedVersion.version }}</p></div><button class="ghost-dark" @click="selectedVersion = null">关闭</button></div>
    <form v-if="versionEditing" @submit.prevent="saveVersionEdit"><label>名称<input v-model="versionEdit.title" /></label><label>关联岗位<select v-model="versionEdit.source_job_id"><option value="">不关联</option><option v-for="job in jobs" :key="job.job_id" :value="job.job_id">{{ job.company_name }} · {{ job.title }}</option></select></label><label>简历文本<textarea v-model="versionEdit.content_text" rows="20"></textarea></label><div class="form-actions"><button class="primary">保存修改</button></div></form>
    <pre v-else>{{ selectedVersion.content_text }}</pre>
  </section>
</template>
