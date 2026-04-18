/**
 * Mission domain types — status, tier, CRUD, team members.
 */

import type { AgentConfigSummary } from './agent'

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
