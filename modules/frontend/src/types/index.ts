/**
 * Shared TypeScript types.
 *
 * Add shared type definitions here.
 */

// API Response types
export interface ApiResponse<T> {
  success: boolean
  data: T | null
  error: ApiError | null
  metadata: ResponseMetadata
}

export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown>
}

export interface ResponseMetadata {
  timestamp: string
  request_id: string | null
}

// Pagination types
export interface PaginationInfo {
  total?: number
  limit: number
  cursor?: string
  next_cursor?: string
  has_more: boolean
}

export interface PaginatedResponse<T> {
  success: boolean
  data: T[]
  error: null
  metadata: ResponseMetadata
  pagination: PaginationInfo
}

// Auth types
export interface LoginRequest {
  email: string
  password: string
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: UserResponse
}

export interface TokenRefreshResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

// User types
export interface UserResponse {
  id: string
  email: string
  display_name: string
  system_role: 'viewer' | 'user' | 'admin'
  is_active: boolean
  is_service_account: boolean
  last_login_at: string | null
  current_mission_id: string | null
  current_mission_name: string | null
  created_at: string
  updated_at: string
}

// Mission types
export type MissionStatus = 'active' | 'paused' | 'archived'
export type MissionTier = 'user' | 'platform'

export interface MissionListItem {
  id: string
  name: string
  description: string
  brief: string | null
  status: MissionStatus
  tier: MissionTier
  owner_id: string
  budget_ceiling_usd: number | null
  execution_environment: string | null
  created_at: string
  updated_at: string
}

export interface MissionResponse extends MissionListItem {
  team_id: string | null
  default_roster: string
  repo_url: string | null
  repo_root: string | null
}

export interface MissionCreateRequest {
  name: string
  description: string
  brief?: string
  owner_id: string
  tier?: MissionTier
  budget_ceiling_usd?: number
  repo_url?: string
}

export interface MissionUpdateRequest {
  description?: string
  brief?: string
  status?: MissionStatus
  budget_ceiling_usd?: number | null
  repo_url?: string
  execution_environment?: string | null
}

// Agent Catalog types
export interface AgentCatalogItem {
  id: string
  agent_name: string
  agent_type: 'vertical' | 'horizontal' | 'system'
  version: string
  description: string
  enabled: boolean
  visibility: string
  keywords: string[]
  tools: string[]
  model_config_json: { name?: string; temperature?: number; max_tokens?: number }
  scope: { read?: string[]; write?: string[] }
}

export interface AgentCatalogDetail extends AgentCatalogItem {
  system_prompt: string
  model_config_json: Record<string, unknown>
  scope: Record<string, unknown>
  interface: Record<string, unknown> | null
  constraints: Record<string, unknown>
  created_at: string
  updated_at: string
}

// Mission Team types
export interface AgentConfigSummary {
  agent_name: string
  agent_type: string
  description: string
  model: {
    name?: string
    temperature?: number
    max_tokens?: number
  }
  tools: string[]
  scope: { read?: string[]; write?: string[] }
  constraints: {
    timeout_seconds?: number
    cost_ceiling_usd?: number
    retry_budget?: number
  }
  chat_enabled: boolean
}

export interface MissionTeamMember {
  id: string
  mission_id: string
  agent_catalog_id: string
  user_prompt: string | null
  user_prompt_version: number
  enabled: boolean
  display_order: number
  custom_constraints: Record<string, unknown> | null
  created_at: string
  updated_at: string
  agent: AgentConfigSummary | null
}

export interface MissionTeamAddRequest {
  agent_catalog_id: string
  user_prompt?: string
  display_order?: number
}

export interface UserPromptUpdateRequest {
  content: string
  changed_by: string
  change_reason?: string
}

export interface PromptVersion {
  version: number
  content: string
  changed_by: string
  change_reason: string | null
  created_at: string
}

export interface PromptHistoryResponse {
  member_id: string
  versions: PromptVersion[]
}

// Workflow types
export interface WorkflowListItem {
  workflow_name: string
  description: string
  version: number
  enabled: boolean
  trigger_type: string
  step_count: number
  budget_usd: number
  objective_category: string
  objective_priority: string
  objective_owner: string
}

export interface WorkflowStep {
  id: string
  description: string | null
  capability: string
  roster: string
  complexity_tier: string
  cost_ceiling_usd: number | null
  environment: string
  input: Record<string, unknown>
  output_mapping: {
    summary_key: string | null
    field_mappings: { source_task: string; source_field: string; target_key: string }[]
  } | null
  depends_on: string[]
  timeout_seconds: number | null
  max_refinement_rounds: number
  termination: string
  max_iterations: number | null
}

export interface WorkflowDetail {
  workflow_name: string
  description: string
  objective: {
    statement: string
    category: string
    owner: string
    priority: string
    regulatory_reference: string | null
  }
  version: number
  enabled: boolean
  trigger: {
    type: string
    schedule: string | null
    event_type: string | null
    match_patterns: string[]
  }
  budget: { max_cost_usd: number; max_tokens: number | null }
  context_keys: string[]
  steps: WorkflowStep[]
}

// Mission workflow (DB-stored) types
export interface MissionWorkflow {
  id: string
  name: string
  description: string
  version: number
  enabled: boolean
  trigger_type: string
  step_count: number
  designed_by: string
  locked_at: string | null
}

// Workflow Schedule types
export interface WorkflowSchedule {
  id: string
  workflow_definition_id: string
  mission_id: string
  cron_expression: string
  timezone: string
  enabled: boolean
  description: string
  budget_per_run_usd: number | null
  max_iterations: number | null
  iteration_count: number
  cooldown_seconds: number
  last_fired_at: string | null
  next_fire_at: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export interface WorkflowScheduleCreateRequest {
  workflow_definition_id: string
  cron_expression: string
  timezone?: string
  description?: string
  budget_per_run_usd?: number
  max_iterations?: number
  cooldown_seconds?: number
}

export interface WorkflowScheduleUpdateRequest {
  cron_expression?: string
  timezone?: string
  enabled?: boolean
  description?: string
  budget_per_run_usd?: number | null
  max_iterations?: number | null
  cooldown_seconds?: number
}

// Architect types
export interface ArchitectChatResponse {
  response: string
  usage: string | null
}

// Execution / Run types
export interface ExecutionRecord {
  id: string
  session_id: string
  roster_name: string | null
  status: string
  total_cost_usd: number
  started_at: string | null
  completed_at: string | null
  parent_execution_record_id: string | null
  created_at: string
  updated_at: string
}

export interface TaskExecution {
  id: string
  task_id: string
  agent_name: string
  status: string
  output_data: Record<string, unknown> | null
  token_usage: Record<string, unknown> | null
  cost_usd: number
  duration_seconds: number | null
  verification_outcome: Record<string, unknown> | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ExecutionDecision {
  id: string
  decision_type: string
  task_id: string | null
  reasoning: string
  created_at: string
}

export interface ExecutionRecordDetail extends ExecutionRecord {
  objective_statement: string | null
  objective_category: string | null
  task_plan_json: Record<string, unknown> | null
  execution_outcome_json: Record<string, unknown> | null
  planning_thinking_trace: string | null
  task_executions: TaskExecution[]
  decisions: ExecutionDecision[]
}

export interface ExecutionCostBreakdown {
  execution_id: string
  total_cost_usd: number
  task_costs: {
    task_id: string
    agent_name: string
    cost_usd: number
    input_tokens: number
    output_tokens: number
    status: string
    duration_seconds: number | null
  }[]
  model_costs: Record<string, number>
  attempt_count: number
  total_input_tokens: number
  total_output_tokens: number
}

// Session / Chat types
export interface SessionListItem {
  id: string
  status: string
  goal: string | null
  mission_id: string | null
  agent_id: string | null
  total_cost_usd: number
  created_at: string
  last_activity_at: string
}

export interface SessionResponse {
  id: string
  status: string
  user_id: string | null
  agent_id: string | null
  goal: string | null
  total_cost_usd: number
  cost_budget_usd: number | null
  created_at: string
  updated_at: string
  last_activity_at: string
}

export interface SessionCreateRequest {
  goal?: string
  mission_id?: string
  agent_id?: string
  cost_budget_usd?: number
}

export interface SessionMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result' | 'error'
  content: string
  sender_id: string | null
  model: string | null
  input_tokens: number | null
  output_tokens: number | null
  cost_usd: number | null
  tool_name: string | null
  tool_call_id: string | null
  created_at: string
}

export interface SessionMessageCreateRequest {
  content: string
  role: 'user'
  sender_id?: string
}

// Admin types
export interface AdminMetricsOverview {
  user_count: number
  mission_count: number
  workflow_count: number
  execution_count: number
  total_cost_usd: number
  active_sessions: number
}

export interface AdminCostBreakdown {
  by_agent: { agent_name: string; cost_usd: number; run_count: number }[]
  by_status: { status: string; cost_usd: number; count: number }[]
  total_cost_usd: number
}

export interface AdminAgentStats {
  agent_name: string
  run_count: number
  total_cost_usd: number
  avg_duration_seconds: number
}

export interface HealthCheck {
  status: string
  checks: Record<string, { status: string; latency_ms?: number; error?: string }>
}

export interface ApiKeyResponse {
  id: string
  name: string
  key_prefix: string
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  created_at: string
}

export interface ApiKeyCreateResponse extends ApiKeyResponse {
  key: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

// Execution create/execute types
export interface ExecutionCreateRequest {
  objective: string
  triggered_by: string
  mission_id?: string
  roster_ref?: string
  complexity_tier?: string
  cost_ceiling_usd?: number
}

export interface ExecutionCreateResponse {
  id: string
  session_id: string
  status: string
}

// Drawer types
export type DrawerContentType =
  | 'run-events'
  | 'agent-events'
  | 'prompt-history'
  | 'architect-chat'
  | 'event-log'
  | 'output-preview'
  | 'cost-breakdown'
  | 'agent-detail'

// Notification types
export interface Notification {
  id: string
  type: 'gate_approval' | 'run_failed' | 'run_completed' | 'budget_warning'
  title: string
  body: string
  mission_id: string | null
  data: Record<string, unknown>
  read: boolean
  created_at: string
}
