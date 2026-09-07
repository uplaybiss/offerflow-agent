<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, formatTime } from '../api'

type Candidate = {
  version: number; full_name: string; email: string; phone: string; graduation_year: string; degree: string
  target_roles: string[]; preferred_cities: string[]; excluded_companies: string[]; preferences: Record<string, unknown>
  skills: string[]; current_resume_text: string; current_resume_parsed: Record<string, unknown>; current_resume_filename: string
  current_resume_sha256: string; resume_updated_at: string
}
type Capabilities = { resume_file_types: string[]; max_resume_bytes: number; llm_available: boolean; llm_provider: string; llm_model: string; preview_persistence: string }
type ResumePreview = Partial<Candidate> & { current_resume_parsed: Record<string, unknown> }

const model = reactive({ version: 1, full_name: '', email: '', phone: '', graduation_year: '', degree: '', target_roles: '', preferred_cities: '', excluded_companies: '', skills: '', current_resume_text: '', current_resume_filename: '', current_resume_parsed: '{}', preferences: '{}' })
const saved = ref<Candidate | null>(null)
const capabilities = ref<Capabilities | null>(null)
const localPreview = ref(false)
const extraction = ref<{ filename: string; file_type: string; sha256: string; character_count: number } | null>(null)
const message = ref('')
const error = ref('')
const extracting = ref(false)
const parsing = ref(false)
const split = (value: string) => value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean)

function fill(item: Candidate) {
  saved.value = item
  Object.assign(model, {
    ...item,
    target_roles: item.target_roles.join('，'),
    preferred_cities: item.preferred_cities.join('，'),
    excluded_companies: item.excluded_companies.join('，'),
    skills: item.skills.join('，'),
    current_resume_parsed: JSON.stringify(item.current_resume_parsed, null, 2),
    preferences: JSON.stringify(item.preferences, null, 2),
  })
}

async function load() {
  const [candidate, parser] = await Promise.all([
    api.get<{ candidate: Candidate }>('/api/candidate'),
    api.get<Capabilities>('/api/parsing/capabilities'),
  ])
  fill(candidate.candidate)
  capabilities.value = parser
}

async function handleResumeFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  extracting.value = true; error.value = ''; message.value = ''
  try {
    const body = new FormData(); body.append('file', file)
    const result = await api.upload<{ extraction: { filename: string; file_type: string; text: string; sha256: string; character_count: number }; persisted: boolean }>('/api/parsing/resume/extract', body)
    model.current_resume_filename = result.extraction.filename
    model.current_resume_text = result.extraction.text
    extraction.value = result.extraction
    localPreview.value = true
    message.value = '文本已提取到当前页面，尚未覆盖正式档案'
  } catch (reason) { error.value = (reason as Error).message }
  finally { extracting.value = false; (event.target as HTMLInputElement).value = '' }
}

async function parseResume() {
  if (!model.current_resume_text.trim()) { error.value = '请先上传或粘贴简历文本'; return }
  parsing.value = true; error.value = ''; message.value = ''
  try {
    const result = await api.post<{ preview: ResumePreview; persisted: boolean; requires_confirmation: boolean }>('/api/parsing/resume/preview', { text: model.current_resume_text })
    const preview = result.preview
    model.full_name = preview.full_name || ''
    model.email = preview.email || ''
    model.phone = preview.phone || ''
    model.graduation_year = preview.graduation_year || ''
    model.degree = preview.degree || ''
    model.target_roles = (preview.target_roles || []).join('，')
    model.preferred_cities = (preview.preferred_cities || []).join('，')
    model.skills = (preview.skills || []).join('，')
    model.current_resume_parsed = JSON.stringify(preview.current_resume_parsed || {}, null, 2)
    localPreview.value = true
    message.value = 'AI 结构化预览已填入页面，请校对后再确认保存'
  } catch (reason) { error.value = (reason as Error).message }
  finally { parsing.value = false }
}

async function save() {
  message.value = ''; error.value = ''
  try {
    const payload = {
      ...model,
      target_roles: split(model.target_roles), preferred_cities: split(model.preferred_cities),
      excluded_companies: split(model.excluded_companies), skills: split(model.skills),
      current_resume_parsed: JSON.parse(model.current_resume_parsed || '{}'),
      preferences: JSON.parse(model.preferences || '{}'),
    }
    fill((await api.put<{ candidate: Candidate }>('/api/candidate', payload)).candidate)
    localPreview.value = false; extraction.value = null; message.value = '候选人档案与当前简历已确认保存'
  } catch (reason) { error.value = (reason as Error).message }
}

onMounted(() => load().catch(reason => { error.value = (reason as Error).message }))
</script>

<template>
  <header class="page-header"><div><span class="eyebrow">PROFILE · PHASE 2</span><h1>候选人 360</h1><p>上传与解析先形成本页预览，只有确认保存才覆盖当前档案。</p></div><button class="primary" @click="save">确认保存档案</button></header>
  <div v-if="capabilities" class="capability-bar"><span>TXT / PDF ≤ {{ Math.round(capabilities.max_resume_bytes / 1024 / 1024) }} MB</span><span :class="capabilities.llm_available ? 'available' : 'muted'">{{ capabilities.llm_available ? `AI 解析可用 · ${capabilities.llm_model}` : '未配置模型 · 可手工维护' }}</span><span v-if="localPreview" class="preview-flag">未保存预览</span></div>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
  <div class="content-grid profile-grid">
    <section class="panel form-panel"><div class="panel-title"><h2>基本信息</h2><span>正式版本 v{{ model.version }}</span></div><div class="form-grid"><label>姓名<input v-model="model.full_name" /></label><label>邮箱<input v-model="model.email" type="email" /></label><label>手机<input v-model="model.phone" /></label><label>毕业年份<input v-model="model.graduation_year" placeholder="2027" /></label><label>学历<input v-model="model.degree" /></label><label>目标岗位<input v-model="model.target_roles" placeholder="AI应用，测试开发" /></label><label class="wide">期望城市<input v-model="model.preferred_cities" /></label><label class="wide">排除公司<input v-model="model.excluded_companies" /></label></div></section>
    <section class="panel form-panel"><div class="panel-title"><h2>结构化技能与硬条件</h2><span>JSON 字段</span></div><label>具体技能（逗号或换行分隔）<textarea v-model="model.skills" rows="4" placeholder="Python，FastAPI，LangChain"></textarea></label><p class="field-help">匹配时会分别生成 canonical skill 与 skill category；同类技能不会互相命中。</p><label>其他求职偏好（JSON）<textarea v-model="model.preferences" rows="7" placeholder='{"accepted_employment_types":["全职"],"languages":["英语"],"requires_visa":false}'></textarea></label></section>
    <section class="panel form-panel full">
      <div class="panel-title"><div><h2>当前简历</h2><p>文件提取和 AI 解析都不会直接写数据库。</p></div><span v-if="saved?.current_resume_sha256">正式文本 SHA-256 {{ saved.current_resume_sha256.slice(0, 12) }}…</span></div>
      <div class="resume-actions"><label class="file-button">{{ extracting ? '提取中…' : '上传 TXT / PDF' }}<input type="file" accept=".txt,.pdf,text/plain,application/pdf" :disabled="extracting" @change="handleResumeFile" /></label><button type="button" class="secondary" :disabled="parsing || !capabilities?.llm_available" @click="parseResume">{{ parsing ? '解析中…' : '生成 AI 结构化预览' }}</button><span v-if="extraction">{{ extraction.file_type.toUpperCase() }} · {{ extraction.character_count }} 字符 · {{ extraction.sha256.slice(0, 12) }}…</span></div>
      <label>文件名<input v-model="model.current_resume_filename" placeholder="resume.pdf" /></label>
      <div class="split-edit"><label>简历文本<textarea v-model="model.current_resume_text" rows="18" placeholder="上传 TXT/PDF 或直接粘贴当前简历文本"></textarea></label><label>结构化预览（JSON，可校对）<textarea v-model="model.current_resume_parsed" rows="18"></textarea></label></div>
      <small>正式档案更新时间：{{ saved?.resume_updated_at ? formatTime(saved.resume_updated_at) : '尚未保存简历' }}</small>
    </section>
  </div>
</template>
