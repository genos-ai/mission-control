import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { DollarSign } from 'lucide-react'
import { useMissionCosts } from '@/hooks/use-missions'
import { useMissionBudget } from '@/hooks/use-mission-budget'
import { DocumentPage } from '@/components/layout/document-page'
import { EmptyState } from '@/components/ui/empty-state'
import { Segmented } from '@/components/ui/segmented'
import { Spinner } from '@/components/ui/spinner'
import { CostSummary } from '@/components/mission/cost-summary'
import { CostCallsPanel } from '@/components/mission/cost-calls-panel'
import {
  CachePerformancePanel,
  CostByAgentPanel,
  OutputEfficiencyCallout,
} from '@/components/mission/cost-agent-panels'

// The API takes 24h, 7d and 30d, and no timeframe at all for all-time.
const RANGES = [
  { label: 'Today', value: '24h' },
  { label: '7 days', value: '7d' },
  { label: '30 days', value: '30d' },
  { label: 'All time', value: 'all' },
] as const

type Range = (typeof RANGES)[number]['value']

export default function CostsTab() {
  const { id } = useParams<{ id: string }>()
  const [range, setRange] = useState<Range>('all')
  const { data, isLoading } = useMissionCosts(id, range === 'all' ? undefined : range)
  const { data: budget } = useMissionBudget(id)

  return (
    <DocumentPage className="gap-4">
      <div className="flex items-center justify-between gap-3 pt-2">
        <h2 className="text-base font-medium">Mission costs</h2>
        <Segmented
          label="Time range"
          value={range}
          onChange={setRange}
          options={RANGES.map(({ label, value }) => ({ label, value }))}
        />
      </div>

      {isLoading ? (
        <div className="flex justify-center p-12">
          <Spinner className="h-5 w-5" />
        </div>
      ) : !data || data.summary.total_calls === 0 ? (
        <EmptyState
          icon={<DollarSign className="h-4 w-4" />}
          title={range === 'all' ? 'No cost data yet for this mission.' : 'No calls in this time range.'}
          description="Cost tracking begins when agents are dispatched."
        />
      ) : (
        <>
          <CostSummary data={data} ceiling={budget?.lifetime_usd ?? null} allTime={range === 'all'} />

          <div className="grid grid-cols-[repeat(auto-fit,minmax(340px,1fr))] items-start gap-4">
            <CostByAgentPanel agents={data.by_agent} />
            <div className="flex flex-col gap-4">
              <CachePerformancePanel rows={data.cache_performance} />
              <OutputEfficiencyCallout rows={data.output_efficiency} />
            </div>
          </div>

          <CostCallsPanel calls={data.expensive_calls} />
        </>
      )}
    </DocumentPage>
  )
}
