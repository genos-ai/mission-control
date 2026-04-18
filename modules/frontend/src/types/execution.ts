/**
 * Execution / run types — records, tasks, decisions, cost breakdown.
 */

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
  // Plan 46 Phase 2 #3: task count denormalised from the eager-
  // loaded task_executions relationship for Run History row rendering.
  task_count: number
  // Plan 56 Phase B: background task tracking
  task_type: string | null
  task_params: Record<string, unknown> | null
  temporal_workflow_id: string | null
  mission_id: string | null
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
