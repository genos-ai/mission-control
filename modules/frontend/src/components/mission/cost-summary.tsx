import { StatCard } from '@/components/ui/stat-card'
import { fmtCost, fmtUsd } from '@/lib/format'
import type { MissionCostsResponse } from '@/types'

interface CostSummaryProps {
  data: MissionCostsResponse
  /** The mission's spend ceiling, when it has one. */
  ceiling: number | null | undefined
  /** The budget counts all-time spend, so it only sits beside the all-time total. */
  allTime: boolean
}

/** The four headline figures of the Costs screen, straight from the response's summary. */
export function CostSummary({ data, ceiling, allTime }: CostSummaryProps) {
  const { summary, by_agent } = data
  const agentCount = by_agent.length

  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
      <StatCard
        label="Total cost"
        value={fmtUsd(summary.total_cost_usd)}
        hint={allTime && ceiling != null ? `of ${fmtUsd(ceiling)} budget` : undefined}
      />
      <StatCard
        label="LLM calls"
        value={summary.total_calls.toLocaleString()}
        hint={`across ${agentCount} ${agentCount === 1 ? 'agent' : 'agents'}`}
      />
      <StatCard label="Avg per call" value={fmtCost(summary.avg_cost_per_call)} />
      <StatCard
        label="Cache hit rate"
        value={`${(summary.cache_hit_rate * 100).toFixed(0)}%`}
        hint="of input tokens read from cache"
      />
    </div>
  )
}
