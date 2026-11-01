import { StatCard } from '@/components/ui/stat-card'
import { fmtCost, fmtUsd } from '@/lib/format'
import type { TokenEconomicsSummary } from '@/types'

/** The four headline figures of Token economics, straight from the response's summary. */
export function TokenSummary({ summary }: { summary: TokenEconomicsSummary }) {
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
      <StatCard label="Total cost" value={fmtUsd(summary.total_cost_usd)} />
      <StatCard label="Cache hit rate" value={`${(summary.cache_hit_rate * 100).toFixed(0)}%`} />
      <StatCard label="Avg cost per call" value={fmtCost(summary.avg_cost_per_call)} />
      <StatCard label="Output ratio" value={`${summary.output_ratio.toFixed(1)}x`} />
    </div>
  )
}
