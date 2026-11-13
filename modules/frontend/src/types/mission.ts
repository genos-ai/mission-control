/**
 * Mission domain types — status, tier, CRUD, team members.
 */

import type { AgentConfigSummary } from './agent'

// Mission types
export type MissionStatus = 'active' | 'paused' | 'archived'
export type MissionTier = 'user' | 'platform'
export type MissionPauseReason =
  | 'user'
  | 'budget_run_cap'
  | 'budget_monthly_cap'
  | 'budget_lifetime_cap'
  | 'gate_timeout'

export interface MissionListItem {
  id: string
  name: string
  description: string
  brief: string | null
  status: MissionStatus
  tier: MissionTier
  owner_id: string
  /** All-time LLM spend, the same figure as the Costs tab; 0 when no calls are recorded. */
  spent_usd: number
  execution_environment: string | null
  /** Set exactly when status is 'paused'. */
  paused_reason: MissionPauseReason | null
  paused_at: string | null
  created_at: string
  updated_at: string
}

export interface MissionResponse extends MissionListItem {
  team_id: string | null
  default_roster: string
  repo_url: string | null
  repo_root: string | null
}

export type GateMode = 'interactive' | 'manual' | 'ai_assisted' | 'autonomous'

export interface MissionCreateRequest {
  name: string
  description: string
  brief?: string
  owner_id: string
  gate_mode: GateMode
  tier?: MissionTier
  budget_per_run_usd?: number
  budget_per_month_usd?: number
  budget_lifetime_usd?: number
  repo_url?: string
}

export interface MissionUpdateRequest {
  description?: string
  brief?: string
  status?: MissionStatus
  repo_url?: string
  execution_environment?: string | null
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

// Per-mission cost breakdown (Plan 60)

export interface MissionCostSummary {
  total_cost_usd: number
  total_calls: number
  avg_cost_per_call: number
  cache_hit_rate: number
  output_ratio: number
}

export interface MissionCostAgent {
  agent_name: string
  call_count: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  thinking_tokens: number
  total_cost_usd: number
}

export interface MissionCostCache {
  agent_name: string
  total_input_tokens: number
  cache_read_tokens: number
  cache_hit_rate: number
}

export interface MissionCostEfficiency {
  agent_name: string
  avg_input_tokens: number
  avg_output_tokens: number
  output_input_ratio: number
  flag: 'ok' | 'high' | 'critical'
}

export interface MissionCostCall {
  id: string
  created_at: string
  agent_name: string
  model: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  thinking_tokens: number
  cost_usd: number
  latency_ms: number | null
}

export interface MissionCostsResponse {
  mission_id: string
  summary: MissionCostSummary
  by_agent: MissionCostAgent[]
  cache_performance: MissionCostCache[]
  output_efficiency: MissionCostEfficiency[]
  expensive_calls: MissionCostCall[]
}
