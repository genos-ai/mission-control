/**
 * Session / chat types — list items, messages, create requests.
 */

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
  thinking: string | null
  target_agent: string | null
  status: 'streaming' | 'complete' | 'failed'
  created_at: string
  updated_at: string | null
}

export interface SessionMessageCreateRequest {
  content: string
  role: 'user'
  sender_id?: string
}
