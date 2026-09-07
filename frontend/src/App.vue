<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, setTimeZone } from './api'
import type { User } from './types'
import AppSidebar from './components/AppSidebar.vue'
import LoginView from './views/LoginView.vue'
import WorkbenchView from './views/WorkbenchView.vue'
import JobCenterView from './views/JobCenterView.vue'
import ApplicationTrackerView from './views/ApplicationTrackerView.vue'
import Candidate360View from './views/Candidate360View.vue'
import ResumeCenterView from './views/ResumeCenterView.vue'
import CareerAgentView from './views/CareerAgentView.vue'
import AgentOpsView from './views/AgentOpsView.vue'

type Page = 'workbench' | 'jobs' | 'resumes' | 'applications' | 'candidate' | 'agent' | 'agentops'
const user = ref<User | null>(null)
const page = ref<Page>('workbench')
const checking = ref(true)
const resumeJobId = ref('')

onMounted(async () => {
  try {
    const health = await api.get<{ timezone: string }>('/api/health'); setTimeZone(health.timezone)
    user.value = (await api.get<{ user: User }>('/api/auth/me')).user
  } catch { user.value = null }
  finally { checking.value = false }
})

async function logout() { await api.post('/api/auth/logout'); user.value = null }
function openResume(jobId = '') { resumeJobId.value = jobId; page.value = 'resumes' }
</script>

<template>
  <div v-if="checking" class="loading-screen">OfferFlow 正在载入…</div>
  <LoginView v-else-if="!user" @logged-in="user = $event" />
  <div v-else class="app-shell">
    <AppSidebar :page="page" :username="user.username" :role="user.role" @select="page = $event" @logout="logout" />
    <main class="page-shell">
      <WorkbenchView v-if="page === 'workbench'" @open-applications="page = 'applications'" />
      <JobCenterView v-else-if="page === 'jobs'" @optimize-resume="openResume" />
      <ResumeCenterView v-else-if="page === 'resumes'" :initial-job-id="resumeJobId" />
      <ApplicationTrackerView v-else-if="page === 'applications'" />
      <Candidate360View v-else-if="page === 'candidate'" />
      <CareerAgentView v-else-if="page === 'agent'" />
      <AgentOpsView v-else />
    </main>
  </div>
</template>
