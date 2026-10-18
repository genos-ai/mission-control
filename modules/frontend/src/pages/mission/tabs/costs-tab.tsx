import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2, DollarSign, Zap, TrendingUp, AlertTriangle } from 'lucide-react'
import { useMissionCosts } from '@/hooks/use-missions'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { StatCard } from '@/components/ui/stat-card'
import { fmtTokens } from '@/lib/format'

const FILTERS = [
  { label: 'All Time', value: undefined },
  { label: 'Today', value: '24h' },
  { label: '7 Days', value: '7d' },
  { label: '30 Days', value: '30d' },
] as const

type FilterValue = (typeof FILTERS)[number]['value']

export default function CostsTab() {
  const { id } = useParams<{ id: string }>()
  const [timeframe, setTimeframe] = useState<FilterValue>(undefined)
  const { data, isLoading } = useMissionCosts(id, timeframe)

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!data || data.summary.total_calls === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-muted-foreground">
        <DollarSign className="h-8 w-8 mb-2 opacity-40" />
        <p className="text-sm">No cost data yet for this mission.</p>
        <p className="text-xs mt-1">Cost tracking begins when agents are dispatched.</p>
      </div>
    )
  }

  const { summary, by_agent, cache_performance, output_efficiency, expensive_calls } = data

  return (
    <div className="p-6 space-y-6">
      {/* Timeframe filter */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-foreground">Mission Costs</h3>
        <div className="flex gap-1 rounded-md border p-1">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              onClick={() => setTimeframe(f.value)}
              className={`px-3 py-1 text-xs font-medium rounded ${
                timeframe === f.value
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          icon={<DollarSign className="h-4 w-4" />}
          label="Total Cost"
          value={`$${summary.total_cost_usd.toFixed(2)}`}
        />
        <StatCard
          icon={<Zap className="h-4 w-4" />}
          label="Cache Hit Rate"
          value={`${(summary.cache_hit_rate * 100).toFixed(0)}%`}
        />
        <StatCard
          label="LLM Calls"
          value={summary.total_calls}
        />
        <StatCard
          icon={<TrendingUp className="h-4 w-4" />}
          label="Output Ratio"
          value={`${summary.output_ratio.toFixed(1)}x`}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Agent Breakdown */}
        <Panel>
          <PanelHeader title="Cost by Agent" />
          <PanelContent>
            <div className="space-y-2">
              {by_agent.map((a) => (
                <div key={a.agent_name} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="truncate max-w-[180px]">{a.agent_name}</span>
                    <Badge variant="secondary" className="text-[9px]">
                      {a.call_count}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{fmtTokens(a.input_tokens)} in</span>
                    <span>{fmtTokens(a.output_tokens)} out</span>
                    <span className="font-mono">${a.total_cost_usd.toFixed(4)}</span>
                  </div>
                </div>
              ))}
            </div>
          </PanelContent>
        </Panel>

        {/* Cache Performance */}
        <Panel>
          <PanelHeader title="Cache Performance" />
          <PanelContent>
            <div className="space-y-2">
              {cache_performance.map((c) => (
                <div key={c.agent_name} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[180px]">{c.agent_name}</span>
                  <Badge
                    variant={c.cache_hit_rate >= 0.6 ? 'success' : c.cache_hit_rate >= 0.3 ? 'warning' : 'destructive'}
                    className="text-[9px]"
                  >
                    {(c.cache_hit_rate * 100).toFixed(0)}% hit
                  </Badge>
                </div>
              ))}
              {!cache_performance.length && (
                <p className="text-xs text-muted-foreground">No cache data.</p>
              )}
            </div>
          </PanelContent>
        </Panel>
      </div>

      {/* Output Efficiency */}
      {output_efficiency.some((e) => e.flag !== 'ok') && (
        <Panel>
          <PanelHeader title="Output Efficiency Warnings" />
          <PanelContent>
            <div className="space-y-2">
              {output_efficiency
                .filter((e) => e.flag !== 'ok')
                .map((e) => (
                  <div key={e.agent_name} className="flex items-center justify-between text-sm">
                    <span>{e.agent_name}</span>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-muted-foreground">{e.output_input_ratio}x</span>
                      {e.flag === 'critical' ? (
                        <Badge variant="destructive" className="text-[9px]">
                          <AlertTriangle className="h-3 w-3 mr-0.5" />critical
                        </Badge>
                      ) : (
                        <Badge variant="warning" className="text-[9px]">high</Badge>
                      )}
                    </div>
                  </div>
                ))}
            </div>
          </PanelContent>
        </Panel>
      )}

      {/* Expensive Calls */}
      <Panel>
        <PanelHeader title="Most Expensive Calls" />
        <PanelContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b">
                <th className="text-left py-2 font-medium">Time</th>
                <th className="text-left py-2 font-medium">Agent</th>
                <th className="text-left py-2 font-medium">Model</th>
                <th className="text-right py-2 font-medium">Input</th>
                <th className="text-right py-2 font-medium">Output</th>
                <th className="text-right py-2 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {expensive_calls.map((call) => (
                <tr key={call.id} className="border-b border-border/50">
                  <td className="py-2 text-xs text-muted-foreground">
                    {call.created_at ? new Date(call.created_at).toLocaleTimeString() : '-'}
                  </td>
                  <td className="py-2 truncate max-w-[150px]">{call.agent_name}</td>
                  <td className="py-2 text-xs text-muted-foreground">
                    {call.model.replace('anthropic:', '')}
                  </td>
                  <td className="py-2 text-right font-mono">{fmtTokens(call.input_tokens)}</td>
                  <td className="py-2 text-right font-mono">{fmtTokens(call.output_tokens)}</td>
                  <td className="py-2 text-right font-mono">${call.cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!expensive_calls.length && (
            <p className="text-xs text-muted-foreground py-4 text-center">No calls yet.</p>
          )}
        </PanelContent>
      </Panel>
    </div>
  )
}
