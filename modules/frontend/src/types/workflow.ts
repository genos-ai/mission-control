/**
 * Workflow and architect types.
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
  label?: string | null
  description: string | null
  node_type?: 'agent_step' | 'condition' | 'notification' | 'human_input' | 'tool_call' | 'llm_call' | 'branch' | 'merge' | 'sub_workflow' | 'decision'
  capability: string | null
  condition_config?: {
    expression: string
    true_label: string
    false_label: string
  } | null
  notification_config?: {
    channel: string
    message_template: string
    recipient: string | null
  } | null
  human_input_config?: {
    prompt_message: string
    channel: string
    timeout_hours: number | null
    default_response: string | null
    choices: string[] | null
  } | null
  tool_call_config?: {
    tool_name: string
    tool_args: Record<string, unknown>
  } | null
  llm_call_config?: {
    model: string
    system_prompt: string | null
    prompt_template: string
    temperature: number
    max_tokens: number | null
    structured_output: Record<string, unknown> | null
  } | null
  merge_config?: {
    strategy: string
  } | null
  sub_workflow_config?: {
    workflow_id: string
    workflow_name: string
    pass_context: boolean
    max_depth: number
  } | null
  decision_config?: {
    resolver: 'agent' | 'human' | 'rule'
    model: string | null
    prompt: string | null
    temperature: number
    prompt_message: string | null
    channel: string | null
    timeout_hours: number | null
    default_option: string | null
    expression: string | null
    options: { key: string; label: string }[]
  } | null
  roster: string
  complexity_tier: string
  cost_ceiling_usd: number | null
  environment: string
  container_image?: string | null
  extra_volumes?: { host_path: string; container_path: string; mode: string }[] | null
  input: Record<string, unknown>
  output_mapping: {
    summary_key: string | null
    field_mappings: { source_task: string; source_field: string; target_key: string }[]
  } | null
  condition?: string | null
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

// Edge type for React Flow graph
export interface WorkflowEdge {
  id: string
  source: string
  target: string
  source_handle?: string
  target_handle?: string
  label?: string | null
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
  edges_json: WorkflowEdge[]
}

// Workflow run record (from /workflow-runs API)
export interface WorkflowRunRecord {
  id: string
  workflow_name: string
  workflow_version: number
  status: string
  trigger_type: string
  triggered_by: string
  total_cost_usd: number
  started_at: string | null
  completed_at: string | null
  error_data: Record<string, unknown> | null
  result_summary: string | null
}

// Architect types
export interface ArchitectGraphProposal {
  nodes: Array<{
    id: string
    label: string
    capability: string
    complexity_tier?: string
    environment?: string
  }>
  edges: Array<{
    source: string
    target: string
  }>
}

export interface ArchitectChatResponse {
  response: string
  usage: string | null
  graph_proposal?: ArchitectGraphProposal | null
}
