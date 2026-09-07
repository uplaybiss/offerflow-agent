export type User = { username: string; role: string; active: boolean }

export type Job = {
  job_id: string; company_name: string; title: string; location: string; deadline: string
  employment_type: string; recruitment_cycle: string; graduation_year: string
  status: string; effective_status: string; description_text: string; required_skills: string[]
  preferred_skills: string[]; is_favorite: boolean; source_type: string; source_name: string
  source_url: string; external_job_id: string; company_career_url: string; version: number
  source_metadata: Record<string, unknown>
}

export type MatchEvidence = {
  job_skill: string; candidate_skill: string | null; canonical_skill: string
  skill_category: string; matched: boolean; match_rule: string
}

export type MatchCoverage = {
  matched: number; total: number; ratio: number | null; evidence: MatchEvidence[]
  matched_skills: string[]; missing_skills: string[]
}

export type MatchResult = {
  grade: string; result_fingerprint: string; deterministic: boolean; llm_decided: boolean
  heuristic: { version: string; strong_required_coverage: number; match_required_coverage: number; disclaimer: string }
  hard_conditions: Array<{ name: string; status: string; actual: unknown; expected: unknown; evidence: string }>
  required_coverage: MatchCoverage; preferred_coverage: MatchCoverage
  missing_required_skills: string[]; missing_preferred_skills: string[]
}

export type Application = {
  application_id: string; job_id: string; status: string; next_action: string; notes: string
  version: number; updated_at: string; job: { company_name: string; title: string; location: string }
  events?: Array<{ event_id: string; sequence: number; from_status: string; to_status: string; message: string; created_at: string }>
}

export type Interview = {
  round_id: string; application_id: string; round_no: number; round_type: string; title: string
  status: string; scheduled_at: string; notes: string; result: string; version: number
}

export type Task = {
  task_id: string; title: string; description: string; task_type: string; status: string
  priority: string; due_at: string; version: number; job_id: string; application_id: string; interview_round_id: string
  origin: 'MANUAL' | 'SUGGESTED'; suggestion_key: string; suggestion_source: string
  suggestion_payload: Record<string, unknown>
}

export type TaskSuggestion = {
  suggestion_key: string; persisted: false; requires_confirmation: true
  source: { type: string; id: string; event_at: string }
  task_preview: Omit<Task, 'task_id' | 'version' | 'origin' | 'suggestion_key' | 'suggestion_source' | 'suggestion_payload'>
  trace: { rule_version: string; rule: string; inputs: Record<string, unknown> }
}

export type JobComparison = {
  deterministic: true
  heuristic: MatchResult['heuristic']
  items: Array<{ job: Job; match: MatchResult }>
}

export type SourceRefreshPreview = {
  status: 'NOT_APPLICABLE' | 'UNAVAILABLE' | 'ERROR' | 'PREVIEW'
  job_id: string; base_version: number; persisted: false; job_unchanged: true
  adapter_key: string; update_preview: Partial<Job>; message: string; checked_at: string
}

export type AgentMemory = {
  memory_id: string; chat_id: string; current_job_id: string; current_application_id: string
  current_interview_id: string; current_task_id: string; last_user_goal: string; version: number
}

export type PendingAction = {
  action_id: string; chat_id: string; action_type: 'APPLICATION_TRANSITION' | 'INTERVIEW_PROGRESSION'
  payload: {
    application_id: string; target_status?: string; expected_version?: number; next_action?: string; notes?: string
    current_round_id?: string; current_round_result?: string; next_round_type?: string
    next_round_title?: string; next_round_scheduled_at?: string; task_title?: string; task_due_at?: string
    expected_application_version?: number; expected_interview_version?: number
  }
  status: 'PENDING' | 'EXECUTED' | 'EXPIRED' | 'CANCELLED' | 'FAILED'
  expires_at: string; requires_confirmation: boolean; result: Record<string, unknown>; version: number
}

export type AgentTrace = {
  trace_id: string; status: string; model_name: string; prompt_version: string; toolset_version: string
  config_version_id: string; release_channel: string; release_generation: number
  enabled_tools_sha256: string; enabled_tool_count: number
  history_messages: number; history_messages_used: number
  first_chunk_ms: number | null; total_ms: number | null; input_tokens: number; output_tokens: number
  events: Array<{ sequence: number; event_type: string; tool_name: string; risk: string; status: string; duration_ms: number | null }>
}

export type AgentCapabilities = {
  available: boolean; provider: string; model: string; prompt_version: string; toolset_version: string
  tool_count: number; enabled_tools: string[]; stream_format: string; confirmation_required_for_writes: boolean; trace_policy: string
  stable_version_id: string; canary_version_id: string; canary_percent: number; release_generation: number
}

export type AgentConfiguration = {
  version_id: string; label: string; status: 'DRAFT' | 'VALIDATED' | 'RELEASED'
  settings: { model_name: string; max_retries: number; temperature: number; history_messages: number; prompt_version: string; toolset_version: string; rule_version: string; enabled_tools: string[] }
  settings_sha256: string; validation: { valid?: boolean; errors?: string[] }; revision: number
  created_at: string; validated_at: string
}

export type AgentReleaseState = {
  stable_version_id: string; canary_version_id: string; canary_percent: number
  generation: number; updated_at: string
}

export type RuntimeMetrics = {
  window_minutes: number; since: string; run_count: number; failed_run_count: number; error_rate: number
  total_ms_p50: number | null; total_ms_p95: number | null
  first_chunk_ms_p50: number | null; first_chunk_ms_p95: number | null
  input_tokens: number; output_tokens: number; by_channel: Record<string, number>
  by_configuration: Record<string, number>; cost: null; cost_reason: string
}

export type TraceRun = {
  run_id: string; trace_id: string; run_type: string; status: string; model_name: string
  config_version_id: string; release_channel: string; release_generation: number
  enabled_tools_sha256: string; enabled_tool_count: number
  history_messages: number; history_messages_used: number
  input_tokens: number; output_tokens: number; first_chunk_ms: number | null; total_ms: number | null
  created_at: string; finished_at: string
}

export type EvaluationRun = {
  eval_run_id: string; suite_version: string; baseline_name: string; run_mode: 'EVAL' | 'REPLAY'
  status: string; passed: number; total: number; result_hash: string; baseline_status: string
  config_version_id: string; started_at: string; finished_at: string
  evaluation_kind?: string; live_model?: boolean; sandbox?: boolean
  results?: Array<{ result_id: string; case_id: string; category: string; passed: boolean; duration_ms: number; expected: Record<string, unknown>; actual: Record<string, unknown> }>
}

export type AgentOpsOverview = {
  release: AgentReleaseState; stable: AgentConfiguration | null; canary: AgentConfiguration | null
  versions: AgentConfiguration[]; metrics: RuntimeMetrics; recent_traces: TraceRun[]
  recent_evaluations: EvaluationRun[]; audit: Array<{ event_id: string; event_type: string; generation: number; version_id: string; created_at: string }>
  tool_catalog: Array<{ name: string; risk: string }>
  deployment_mode: string; disclosure: string
}
