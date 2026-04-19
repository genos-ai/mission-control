/**
 * Admin dashboard types — metrics, cost breakdown, agent stats, health.
 */

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

// Token Economics types (Plan 60)

export interface TokenEconomicsSummary {
  total_cost_usd: number
  total_calls: number
  avg_cost_per_call: number
  cache_hit_rate: number
  output_ratio: number
}

export interface TokenBreakdown {
  agent_name: string
  call_count: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  thinking_tokens: number
  total_cost_usd: number
}

export interface CachePerformance {
  agent_name: string
  total_input_tokens: number
  cache_read_tokens: number
  cache_write_5m_tokens: number
  cache_write_1h_tokens: number
  cache_hit_rate: number
  write_to_read_ratio: number
}

export interface CostTimelinePoint {
  timestamp: string
  group: string
  cost_usd: number
}

export interface ExpensiveCall {
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

export interface ModelDistribution {
  model: string
  call_count: number
  call_pct: number
  cost_usd: number
  cost_pct: number
}

export interface OutputEfficiency {
  agent_name: string
  avg_input_tokens: number
  avg_output_tokens: number
  output_input_ratio: number
  flag: 'ok' | 'high' | 'critical'
}
