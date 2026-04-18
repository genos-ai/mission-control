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
