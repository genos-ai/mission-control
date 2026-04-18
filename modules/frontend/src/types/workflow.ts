/**
 * Workflow, schedule, and architect types.
 */

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
