/**
 * Admin dashboard types — metrics, cost breakdown, agent stats, health.
 */

// Admin types
export interface AdminMetricsOverview {
  counts: {
    missions: number
    sessions: number
    execution_records: number
    workflow_runs: number
    agents: number
  }
  total_cost_usd: number
  generated_at: string
}

export interface AdminCostBreakdown {
  by_agent: { agent_name: string; runs: number; total_cost_usd: number }[]
  by_status: { status: string; count: number; total_cost_usd: number }[]
  since: string
  generated_at: string
}

export interface AdminAgentStats {
  agent_name: string
  total_runs: number
  total_cost_usd: number
  avg_cost_usd: number
  /** Null for an agent that has never finished a task. */
  avg_duration_seconds: number | null
}

export interface HealthCheck {
  status: string
  checks: Record<string, { status: string; latency_ms?: number; error?: string; detail?: string }>
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
