import { useExecutionCost } from '@/hooks/use-executions'
import { useDrawerStore } from '@/stores/drawer'
import { Spinner } from '@/components/ui/spinner'

export function CostBreakdownPanel() {
  const { context } = useDrawerStore()
  const executionId = context.executionId as string | undefined
  const { data: breakdown, isLoading } = useExecutionCost(executionId)

  if (isLoading) return <Spinner />
  if (!breakdown) {
    return <p className="text-sm text-muted-foreground">No cost data available.</p>
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Total Cost" value={`$${breakdown.total_cost_usd.toFixed(4)}`} />
        <StatCard label="Attempts" value={String(breakdown.attempt_count)} />
        <StatCard
          label="Input Tokens"
          value={breakdown.total_input_tokens.toLocaleString()}
        />
        <StatCard
          label="Output Tokens"
          value={breakdown.total_output_tokens.toLocaleString()}
        />
      </div>

      {/* Per-task costs */}
      {breakdown.task_costs.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            By Task
          </h4>
          <div className="space-y-1">
            {breakdown.task_costs.map((tc, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
              >
                <div>
                  <span className="font-medium">{tc.agent_name}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {tc.task_id}
                  </span>
                </div>
                <div className="text-right text-xs">
                  <span className="font-medium">${tc.cost_usd.toFixed(4)}</span>
                  <span className="ml-2 text-muted-foreground">
                    {tc.tokens.toLocaleString()} tok
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-model costs */}
      {Object.keys(breakdown.model_costs).length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            By Model
          </h4>
          <div className="space-y-1">
            {Object.entries(breakdown.model_costs).map(([model, cost]) => (
              <div
                key={model}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
              >
                <span className="font-mono text-xs">{model}</span>
                <span className="font-medium">${cost.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border px-3 py-2">
      <p className="text-[10px] font-semibold uppercase text-muted-foreground">
        {label}
      </p>
      <p className="text-base font-bold">{value}</p>
    </div>
  )
}
