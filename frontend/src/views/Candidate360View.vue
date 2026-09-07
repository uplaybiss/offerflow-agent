<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, formatTime } from '../api'

type Candidate = {
  version: number; full_name: string; email: string; phone: string; graduation_year: string; degree: string
  target_roles: string[]; preferred_cities: string[]; excluded_companies: string[]; preferences: Record<string, unknown>
  skills: string[]; current_resume_text: string; current_resume_parsed: Record<string, unknown>
  current_resume_filename: string; resume_updated_at: string
}
type Capabilities = { max_resume_bytes: number; llm_available: boolean }
type ResumePreview = Partial<Candidate> & { current_resume_parsed: Record<string, unknown> }

const model = reactive({
  version: 1, full_name: '', email: '', phone: '', graduation_year: '', degree: '',
  target_roles: '', preferred_cities: '', skills: '', current_resume_text: '', current_resume_filename: '',
})
const parsed = ref<Record<string, unknown>>({})
const preferences = reactive({ employmentTypes: [] as string[], languages: [] as string[], focusCompanies: [] as string[] })
const companyInput = ref('')
const saved = ref<Candidate | null>(null)
const capabilities = ref<Capabilities | null>(null)
const localPreview = ref(false)
const message = ref('')
const error = ref('')
const extracting = ref(false)
const parsing = ref(false)
const split = (value: string) => value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean)
const graduationOptions = computed(() => {
  const year = new Date().getFullYear()
  return [year, year + 1, year + 2, year + 3].map(String)
})
const education = computed(() => Array.isArray(parsed.value.education) ? parsed.value.education as Record<string, unknown>[] : [])
const projects = computed(() => Array.isArray(parsed.value.projects) ? parsed.value.projects as Record<string, unknown>[] : [])
const parsedLanguages = computed(() => Array.isArray(parsed.value.languages) ? parsed.value.languages as string[] : [])
const rawStructure = computed(() => JSON.stringify(parsed.value, null, 2))
const recordLine = (item: Record<string, unknown>) => Object.values(item).filter(value => typeof value === 'string' && value).join(' · ') || '已识别一条记录'

function fill(item: Candidate) {
  saved.value = item
  Object.assign(model, {
    ...item,
    graduation_year: item.graduation_year || '',
    target_roles: item.target_roles.join('，'), preferred_cities: item.preferred_cities.join('，'),
    skills: item.skills.join('，'),
  })
  parsed.value = item.current_resume_parsed || {}
  const prefs = item.preferences || {}
  preferences.employmentTypes = Array.isArray(prefs.accepted_employment_types) ? prefs.accepted_employment_types.map(String) : []
  preferences.languages = Array.isArray(prefs.languages) ? prefs.languages.map(String) : []
  preferences.focusCompanies = Array.isArray(prefs.focus_companies) ? prefs.focus_companies.map(String) : []
}

async function load() {
  const [candidate, parser] = await Promise.all([
    api.get<{ candidate: Candidate }>('/api/candidate'), api.get<Capabilities>('/api/parsing/capabilities'),
  ])
  fill(candidate.candidate); capabilities.value = parser
}

async function handleResumeFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  extracting.value = true; error.value = ''; message.value = ''
  try {
    const body = new FormData(); body.append('file', file)
    const result = await api.upload<{ extraction: { filename: string; text: string } }>('/api/parsing/resume/extract', body)
    model.current_resume_filename = result.extraction.filename
    model.current_resume_text = result.extraction.text
    localPreview.value = true; message.value = '简历文本已提取，请检查后保存'
  } catch (reason) { error.value = (reason as Error).message }
  finally { extracting.value = false; (event.target as HTMLInputElement).value = '' }
}

async function parseResume() {
  if (!model.current_resume_text.trim()) { error.value = '请先上传或粘贴简历文本'; return }
  parsing.value = true; error.value = ''; message.value = ''
  try {
    const result = await api.post<{ preview: ResumePreview }>('/api/parsing/resume/preview', { text: model.current_resume_text })
    const preview = result.preview
    model.full_name = preview.full_name || model.full_name
    model.email = preview.email || model.email; model.phone = preview.phone || model.phone
    model.graduation_year = preview.graduation_year || model.graduation_year; model.degree = preview.degree || model.degree
    model.target_roles = (preview.target_roles || []).join('，'); model.preferred_cities = (preview.preferred_cities || []).join('，')
    model.skills = (preview.skills || []).join('，'); parsed.value = preview.current_resume_parsed || {}
    localPreview.value = true; message.value = '解析结果已填入预览，请核对后保存'
  } catch (reason) { error.value = (reason as Error).message }
  finally { parsing.value = false }
}

function addCompany() {
  const value = companyInput.value.trim()
  if (value && !preferences.focusCompanies.includes(value)) preferences.focusCompanies.push(value)
  companyInput.value = ''
}

async function save() {
  message.value = ''; error.value = ''
  try {
    const existing = saved.value?.preferences || {}
    const payload = {
      ...model,
      target_roles: split(model.target_roles), preferred_cities: split(model.preferred_cities), skills: split(model.skills),
      excluded_companies: [], current_resume_parsed: parsed.value,
      preferences: {
        ...existing,
        accepted_employment_types: preferences.employmentTypes,
        languages: preferences.languages,
        focus_companies: preferences.focusCompanies,
      },
    }
    fill((await api.put<{ candidate: Candidate }>('/api/candidate', payload)).candidate)
    localPreview.value = false; message.value = '个人信息与基础简历已保存'
  } catch (reason) { error.value = (reason as Error).message }
}

onMounted(() => load().catch(reason => { error.value = (reason as Error).message }))
</script>

<template>
  <header class="page-header"><div><h1>个人中心</h1><p>管理你的个人信息、技能和求职偏好，用于岗位匹配和简历优化。</p></div><button class="primary" @click="save">保存</button></header>
  <p v-if="message" class="success">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
  <div class="content-grid profile-grid">
    <section class="panel form-panel">
      <div class="panel-title"><h2>个人信息</h2><span>版本 {{ model.version }}</span></div>
      <div class="form-grid">
        <label>姓名<input v-model="model.full_name" /></label><label>邮箱<input v-model="model.email" type="email" /></label>
        <label>手机<input v-model="model.phone" /></label><label>学历<input v-model="model.degree" /></label>
        <label>应届生届别<select v-model="model.graduation_year"><option value="">请选择</option><option v-for="year in graduationOptions" :key="year" :value="year">{{ year }}届</option><option value="其他">其他</option></select></label>
        <label>目标岗位<input v-model="model.target_roles" placeholder="AI 应用，测试开发" /></label>
        <label class="wide">期望城市<input v-model="model.preferred_cities" placeholder="深圳，上海" /></label>
      </div>
    </section>
    <section class="panel form-panel">
      <div class="panel-title"><h2>技能与求职偏好</h2></div>
      <label>技能<textarea v-model="model.skills" rows="4" placeholder="Python，FastAPI，LangChain"></textarea></label>
      <p class="field-help">填写你能够在面试中实际解释和使用的技能。</p>
      <fieldset><legend>求职类型</legend><label class="inline-check"><input v-model="preferences.employmentTypes" type="checkbox" value="全职" /> 全职</label><label class="inline-check"><input v-model="preferences.employmentTypes" type="checkbox" value="实习" /> 实习</label></fieldset>
      <fieldset><legend>语言</legend><label v-for="language in ['英语','日语','韩语','其他']" :key="language" class="inline-check"><input v-model="preferences.languages" type="checkbox" :value="language" /> {{ language }}</label></fieldset>
      <label>重点公司<div class="tag-editor"><span v-for="company in preferences.focusCompanies" :key="company">{{ company }} <button type="button" @click="preferences.focusCompanies = preferences.focusCompanies.filter(item => item !== company)">×</button></span><input v-model="companyInput" placeholder="输入公司后添加" @keyup.enter.prevent="addCompany" /><button type="button" class="secondary" @click="addCompany">添加</button></div></label>
    </section>
    <section class="panel form-panel full">
      <div class="panel-title"><div><h2>基础简历</h2><p>解析只生成预览，点击页面顶部“保存”后才更新基础简历。</p></div><span v-if="localPreview" class="preview-flag">尚未保存</span></div>
      <div class="resume-actions"><label class="file-button">{{ extracting ? '提取中…' : '上传 TXT / PDF' }}<input type="file" accept=".txt,.pdf,text/plain,application/pdf" :disabled="extracting" @change="handleResumeFile" /></label><button type="button" class="secondary" :disabled="parsing || !capabilities?.llm_available" @click="parseResume">{{ parsing ? '解析中…' : 'AI 解析简历' }}</button><small>文件不超过 {{ Math.round((capabilities?.max_resume_bytes || 0) / 1024 / 1024) }} MB</small></div>
      <label>文件名<input v-model="model.current_resume_filename" placeholder="resume.pdf" /></label>
      <label>简历文本<textarea v-model="model.current_resume_text" rows="18" placeholder="上传文件或直接粘贴基础简历文本"></textarea></label>
      <div v-if="Object.keys(parsed).length" class="resume-preview-cards">
        <article><h3>教育经历</h3><p v-for="(item, index) in education" :key="index">{{ recordLine(item) }}</p><span v-if="!education.length">未识别</span></article>
        <article><h3>核心技能</h3><div class="tag-list"><span v-for="skill in split(model.skills)" :key="skill">{{ skill }}</span></div></article>
        <article><h3>语言</h3><p>{{ parsedLanguages.join('、') || '未识别' }}</p></article>
        <article><h3>项目</h3><p v-for="(item, index) in projects" :key="index">{{ recordLine(item) }}</p><span v-if="!projects.length">未识别</span></article>
      </div>
      <details v-if="Object.keys(parsed).length" class="advanced-details"><summary>查看原始结构</summary><pre>{{ rawStructure }}</pre></details>
      <small>最后更新：{{ saved?.resume_updated_at ? formatTime(saved.resume_updated_at) : '尚未保存' }}</small>
    </section>
  </div>
</template>
