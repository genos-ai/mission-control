import { useState } from 'react'

import {
  useTokenBreakdown,
  useCachePerformance,
  useExpensiveCalls,
  useModelDistribution,
  useOutputEfficiency,
} from '@/hooks/use-admin'
import {
  ModelDistributionPanel,
  TokenCachePanel,
  TokenEfficiencyPanel,
  TokenPanel,
} from '@/components/admin/token-agent-panels'
import { TokenCallsTable } from '@/components/admin/token-calls-table'
import { TokenSummary } from '@/components/admin/token-summary'
import { CostByAgentPanel } from '@/components/mission/cost-agent-panels'
import { Segmented } from '@/components/ui/segmented'
import { Spinner } from '@/components/ui/spinner'

const TIMEFRAMES = ['24h', '7d', '30d'] as const
type Timeframe = (typeof TIMEFRAMES)[number]

export default function TokenEconomicsPage() {
  const [timeframe, setTimeframe] = useState<Timeframe>('7d')

  const { data: breakdown, isLoading } = useTokenBreakdown(timeframe)
  const { data: cache } = useCachePerformance(timeframe)
  const { data: expensive } = useExpensiveCalls(timeframe)
  const { data: models } = useModelDistribution(timeframe)
  const { data: efficiency } = useOutputEfficiency(timeframe)

  return (
    <>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-medium">Token economics</h2>
        <Segmented
          label="Timeframe"
          value={timeframe}
          onChange={setTimeframe}
          options={TIMEFRAMES.map((tf) => ({ label: tf, value: tf }))}
        />
      </div>

      {isLoading ? (
        <div className="flex justify-center p-12">
          <Spinner className="h-5 w-5" />
        </div>
      ) : (
        <>
          {breakdown?.summary && <TokenSummary summary={breakdown.summary} />}

          <div className="grid grid-cols-1 items-start gap-4 min-[1000px]:grid-cols-2">
            {breakdown?.agents.length ? (
              <CostByAgentPanel agents={breakdown.agents} />
            ) : (
              <TokenPanel title="Cost by agent" empty="No data yet." />
            )}
            <ModelDistributionPanel models={models ?? []} />
            <TokenCachePanel rows={cache ?? []} />
            <TokenEfficiencyPanel rows={efficiency ?? []} />
          </div>

          <TokenCallsTable calls={expensive ?? []} />
        </>
      )}
    </>
  )
}
