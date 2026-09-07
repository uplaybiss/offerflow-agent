<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import type { User } from '../types'

const emit = defineEmits<{ loggedIn: [user: User] }>()
const username = ref('demo')
const password = ref('demo')
const error = ref('')
const loading = ref(false)

async function login() {
  error.value = ''; loading.value = true
  try {
    const result = await api.post<{ user: User }>('/api/auth/login', { username: username.value, password: password.value })
    emit('loggedIn', result.user)
  } catch (e) { error.value = (e as Error).message } finally { loading.value = false }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro"><span class="eyebrow">OFFERFLOW · PHASE 3</span><h1>把秋招进度，<br />变成一条清晰的路。</h1><p>从岗位与面试时间生成可追溯建议；所有写入仍由你确认，所有记录仍可编辑。</p></section>
    <form class="login-card" @submit.prevent="login"><h2>欢迎回来</h2><p>登录你的求职工作台</p><label>用户名<input v-model="username" autocomplete="username" /></label><label>密码<input v-model="password" type="password" autocomplete="current-password" /></label><p v-if="error" class="error">{{ error }}</p><button class="primary" :disabled="loading">{{ loading ? '登录中…' : '进入工作台' }}</button><small>本地演示账号：demo / demo</small></form>
  </main>
</template>
