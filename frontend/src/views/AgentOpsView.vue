<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, commandId, formatTime } from '../api'
import type { AgentConfiguration, AgentOpsOverview, AgentTrace, EvaluationRun } from '../types'

const overview = ref<AgentOpsOverview | null>(null)
const selectedTrace = ref<AgentTrace | null>(null)
const selectedEvaluation = ref<EvaluationRun | null>(null)
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const notice = ref('')
const label = ref('candidate-config')
const modelName = ref('')
const maxRetries = ref(2)
const historyMessages = ref(12)
const enabledTools = ref<string[]>([])
const canaryPercent = ref(10)
const baselineName = ref('phase5-stable')

async function load() {
  loading.value = true; error.value = ''
  try {
    overview.value = await api.get<AgentOpsOverview>('/api/agentops/overview?window_minutes=60')
    if (!modelName.value && overview.value.stable) modelName.value = overview.value.stable.settings.model_name
    if (!enabledTools.value.length && overview.value.stable) enabledTools.value = [...overview.value.stable.settings.enabled_tools]
  } catch (err) { error.value = (err as Error).message }
  finally { loading.value = false }
}

async function act(task: () => Promise<unknown>, message: string) {
  actionLoading.value = true; error.value = ''; notice.value = ''
  try { await task(); notice.value = message; await load() }
  catch (err) { error.value = (err as Error).message }
  finally { actionLoading.value = false }
}

async function createDraft() {
  const base = overview.value?.stable?.settings
  if (!base) return
  await act(() => api.post('/api/agentops/configurations', {
    label: label.value,
    settings: { ...base, model_name: modelName.value, max_retries: maxRetries.value, history_messages: historyMessages.value, enabled_tools: enabledTools.value },
  }), '已创建不可变草稿，请校验后再发布。')
}

async function validate(version: AgentConfiguration) {
  await act(() => api.post(`/api/agentops/configurations/${version.version_id}/validate`, {
    expected_revision: version.revision,
  }), '配置校验通过。')
}

async function publish(version: AgentConfiguration, channel: 'STABLE' | 'CANARY') {
  if (!overview.value) return
  await act(() => api.post('/api/agentops/releases', {
    version_id: version.version_id,
    channel,
    canary_percent: channel === 'CANARY' ? canaryPercent.value : 0,
    expected_generation: overview.value!.release.generation,
    command_id: commandId(`agentops:${channel.toLowerCase()}`),
  }), channel === 'STABLE' ? '稳定版本已发布。' : '灰度版本已发布。')
}

async function rollback(version: AgentConfiguration) {
  if (!overview.value) return
  await act(() => api.post('/api/agentops/rollback', {
    target_version_id: version.version_id,
    expected_generation: overview.value!.release.generation,
    command_id: commandId('agentops:rollback'),
    reason: '由 AgentOps 控制台执行',
  }), '已回滚稳定版本并清空灰度。')
}

async function runEvaluation(replay: boolean) {
  await act(async () => {
    const result = await api.post<{ evaluation: EvaluationRun }>(`/api/agentops/evaluations/${replay ? 'replay' : 'run'}`, {
      baseline_name: baselineName.value,
      update_baseline: !replay,
    })
    selectedEvaluation.value = result.evaluation
  }, replay ? '基线回放完成。' : '固定评测完成并更新基线。')
}

async function runContractEvaluation() {
  await act(async () => {
    const result = await api.post<{ evaluation: EvaluationRun }>('/api/agentops/evaluations/contract', {})
    selectedEvaluation.value = result.evaluation
  }, 'Agent Contract / Safety Eval 完成。')
}

async function inspectTrace(traceId: string) {
  try { selectedTrace.value = (await api.get<{ trace: AgentTrace }>(`/api/agentops/traces/${traceId}`)).trace }
  catch (err) { error.value = (err as Error).message }
}

async function inspectEvaluation(runId: string) {
  try { selectedEvaluation.value = (await api.get<{ evaluation: EvaluationRun }>(`/api/agentops/evaluations/${runId}`)).evaluation }
  catch (err) { error.value = (err as Error).message }
}

onMounted(load)
</script>

<template>
  <section>
    <header class="page-header">
      <div><span class="eyebrow">PHASE 5 · CONTROL PLANE</span><h1>AgentOps</h1><p>版本化运行配置、灰度发布、质量监控与可复现评测</p></div>
      <button class="secondary" :disabled="loading" @click="load">刷新</button>
    </header>
    <p v-if="error" class="alert error">{{ error }}</p>
    <p v-if="notice" class="alert success">{{ notice }}</p>
    <div v-if="overview" class="ops-stack">
      <div class="metric-grid">
        <article class="metric-card"><small>发布代次</small><strong>{{ overview.release.generation }}</strong><span>generation CAS</span></article>
        <article class="metric-card"><small>近 60 分钟 Run</small><strong>{{ overview.metrics.run_count }}</strong><span>失败 {{ overview.metrics.failed_run_count }}</span></article>
        <article class="metric-card"><small>总耗时 P50 / P95</small><strong>{{ overview.metrics.total_ms_p50 ?? '—' }} / {{ overview.metrics.total_ms_p95 ?? '—' }}</strong><span>毫秒</span></article>
        <article class="metric-card"><small>首块 P50 / P95</small><strong>{{ overview.metrics.first_chunk_ms_p50 ?? '—' }} / {{ overview.metrics.first_chunk_ms_p95 ?? '—' }}</strong><span>毫秒</span></article>
        <article class="metric-card"><small>错误率</small><strong>{{ (overview.metrics.error_rate * 100).toFixed(1) }}%</strong><span>完成的 Run</span></article>
        <article class="metric-card"><small>输入 / 输出 Token</small><strong>{{ overview.metrics.input_tokens }} / {{ overview.metrics.output_tokens }}</strong><span>不推测费用</span></article>
      </div>

      <div class="ops-columns">
        <article class="panel ops-panel">
          <div class="section-heading"><div><h2>发布状态</h2><p>同一 cohort 在同一 generation 内稳定命中同一通道</p></div></div>
          <div class="release-lanes">
            <div><small>STABLE</small><strong>{{ overview.stable?.label }}</strong><code>{{ overview.release.stable_version_id }}</code><span>{{ overview.stable?.settings.model_name }}</span></div>
            <div><small>CANARY · {{ overview.release.canary_percent }}%</small><strong>{{ overview.canary?.label || '未启用' }}</strong><code>{{ overview.release.canary_version_id || '—' }}</code><span>{{ overview.canary?.settings.model_name || '—' }}</span></div>
          </div>
          <p class="boundary-note">{{ overview.disclosure }}</p>
        </article>

        <article class="panel ops-panel">
          <div class="section-heading"><div><h2>新建配置草稿</h2><p>配置内容创建后不可修改，只能新建版本</p></div></div>
          <div class="form-grid compact-form">
            <label>版本名称<input v-model="label" /></label>
            <label>模型<input v-model="modelName" /></label>
            <label>最大重试<input v-model.number="maxRetries" type="number" min="0" max="5" /></label>
            <label>历史消息数<input v-model.number="historyMessages" type="number" min="1" max="20" /></label>
          </div>
          <div class="tool-whitelist"><strong>Tool Whitelist</strong><label v-for="tool in overview.tool_catalog" :key="tool.name"><input v-model="enabledTools" type="checkbox" :value="tool.name" /><span>{{ tool.name }} · {{ tool.risk }}</span></label></div>
          <button class="primary" :disabled="actionLoading" @click="createDraft">创建不可变草稿</button>
        </article>
      </div>

      <article class="panel ops-panel">
        <div class="section-heading"><div><h2>配置版本</h2><p>草稿需显式校验；发布和回滚都使用 generation CAS 与 command 幂等</p></div><label class="inline-field">灰度比例 %<input v-model.number="canaryPercent" type="number" min="1" max="50" /></label></div>
        <div class="config-list">
          <div v-for="version in overview.versions" :key="version.version_id" class="config-row">
            <div><strong>{{ version.label }}</strong><code>{{ version.version_id }}</code><small>{{ formatTime(version.created_at) }} · rev {{ version.revision }}</small></div>
            <span class="status-pill">{{ version.status }}</span>
            <div class="config-values"><span>{{ version.settings.model_name }}</span><span>retry {{ version.settings.max_retries }}</span><span>history {{ version.settings.history_messages }}</span><span>tools {{ version.settings.enabled_tools.length }}</span></div>
            <div class="row-actions">
              <button v-if="version.status === 'DRAFT'" class="secondary" :disabled="actionLoading" @click="validate(version)">校验</button>
              <template v-else><button class="secondary" :disabled="actionLoading" @click="publish(version, 'CANARY')">发布灰度</button><button class="primary" :disabled="actionLoading" @click="publish(version, 'STABLE')">发布稳定</button><button class="ghost" :disabled="actionLoading" @click="rollback(version)">回滚到此</button></template>
            </div>
          </div>
        </div>
      </article>

      <div class="ops-columns">
        <article class="panel ops-panel">
          <div class="section-heading"><div><h2>固定评测与回放 + Contract Eval</h2><p>业务回归与 Agent Contract/Safety 分开标记，均使用隔离合成数据</p></div></div>
          <label>基线名称<input v-model="baselineName" /></label>
          <div class="button-row"><button class="primary" :disabled="actionLoading" @click="runEvaluation(false)">运行并更新基线</button><button class="secondary" :disabled="actionLoading" @click="runEvaluation(true)">沙箱回放对比</button></div>
          <button class="secondary" :disabled="actionLoading" @click="runContractEvaluation">运行 Agent Contract / Safety Eval（脚本化）</button>
          <p class="boundary-note">career-agent-fixed-v1 是确定性业务回归；career-agent-contract-v1 验证 Tool 路由、参数、隔离与写安全，不代表真实模型效果。真实 Qwen 仅做非 CI smoke。</p>
          <div class="compact-list">
            <button v-for="run in overview.recent_evaluations" :key="run.eval_run_id" @click="inspectEvaluation(run.eval_run_id)"><span><b>{{ run.run_mode }}</b> {{ run.passed }}/{{ run.total }}</span><small>{{ run.baseline_status }} · {{ formatTime(run.started_at) }}</small></button>
          </div>
        </article>

        <article class="panel ops-panel">
          <div class="section-heading"><div><h2>最近 Trace</h2><p>仅展示 allowlist 元数据，不保存聊天、简历或隐藏思维链</p></div></div>
          <div class="compact-list trace-list">
            <button v-for="run in overview.recent_traces" :key="run.trace_id" @click="inspectTrace(run.trace_id)"><span><b>{{ run.status }}</b> {{ run.release_channel }} · {{ run.total_ms ?? '—' }}ms</span><small>{{ run.model_name }} · {{ formatTime(run.created_at) }}</small><code>{{ run.trace_id }}</code></button>
          </div>
        </article>
      </div>

      <article v-if="selectedEvaluation" class="panel ops-panel detail-panel">
        <div class="section-heading"><div><h2>评测详情</h2><p>{{ selectedEvaluation.eval_run_id }} · {{ selectedEvaluation.baseline_status }}</p></div><button class="ghost" @click="selectedEvaluation = null">关闭</button></div>
        <div class="eval-results"><div v-for="item in selectedEvaluation.results || []" :key="item.case_id"><span :class="item.passed ? 'pass' : 'fail'">{{ item.passed ? 'PASS' : 'FAIL' }}</span><strong>{{ item.case_id }}</strong><small>{{ item.category }} · {{ item.duration_ms }}ms</small></div></div>
      </article>

      <article v-if="selectedTrace" class="panel ops-panel detail-panel">
        <div class="section-heading"><div><h2>Trace 时间线</h2><p>{{ selectedTrace.trace_id }} · {{ selectedTrace.release_channel }} / generation {{ selectedTrace.release_generation }} · tools {{ selectedTrace.enabled_tool_count }} · history {{ selectedTrace.history_messages_used }}/{{ selectedTrace.history_messages }}</p></div><button class="ghost" @click="selectedTrace = null">关闭</button></div>
        <div class="trace-timeline"><div v-for="event in selectedTrace.events" :key="event.sequence"><b>#{{ event.sequence }} {{ event.event_type }}</b><span>{{ event.tool_name || 'runtime' }} · {{ event.status }} · {{ event.duration_ms ?? '—' }}ms</span></div></div>
      </article>
    </div>
  </section>
</template>
