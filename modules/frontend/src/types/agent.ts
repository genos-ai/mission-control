/**
 * Agent catalog and config types.
 */

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
  engine: 'pydantic_ai' | 'claude_code' | 'codex' | 'copilot'
  effort: 'low' | 'medium' | 'high' | null
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
