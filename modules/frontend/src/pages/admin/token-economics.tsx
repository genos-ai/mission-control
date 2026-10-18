import { useState } from 'react'
import { Loader2, DollarSign, Zap, TrendingUp, AlertTriangle } from 'lucide-react'
import {
  useTokenBreakdown,
  useCachePerformance,
  useExpensiveCalls,
  useModelDistribution,
  useOutputEfficiency,
} from '@/hooks/use-admin'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Badge } from '@/components/ui/badge'
import { StatusPill } from '@/components/ui/status-pill'
import { StatCard } from '@/components/ui/stat-card'
import { fmtTokens } from '@/lib/format'

const TIMEFRAMES = ['24h', '7d', '30d'] as const
type Timeframe = (typeof TIMEFRAMES)[number]

export default function TokenEconomicsPage() {
  const [timeframe, setTimeframe] = useState<Timeframe>('7d')

  const { data: breakdown, isLoading } = useTokenBreakdown(timeframe)
  const { data: cache } = useCachePerformance(timeframe)
  const { data: expensive } = useExpensiveCalls(timeframe)
  const { data: models } = useModelDistribution(timeframe)
  const { data: efficiency } = useOutputEfficiency(timeframe)

  if (isLoading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const summary = breakdown?.summary

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Token Economics</h2>
        <div className="flex gap-1 rounded-md border p-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-3 py-1 text-xs font-medium rounded ${
                timeframe === tf
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
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
            label="Avg Cost/Call"
            value={`$${summary.avg_cost_per_call.toFixed(4)}`}
          />
          <StatCard
            icon={<TrendingUp className="h-4 w-4" />}
            label="Output Ratio"
            value={`${summary.output_ratio.toFixed(1)}x`}
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        {/* Token Breakdown */}
        <Panel>
          <PanelHeader title="Token Breakdown by Agent" />
          <PanelContent>
            <div className="space-y-2">
              {breakdown?.agents.map((a) => (
                <div key={a.agent_name} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2">
                    <span className="truncate max-w-[180px]">{a.agent_name}</span>
                    <Badge>
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
              {!breakdown?.agents.length && (
                <p className="text-xs text-muted-foreground">No data yet.</p>
              )}
            </div>
          </PanelContent>
        </Panel>

        {/* Model Distribution */}
        <Panel>
          <PanelHeader title="Model Distribution" />
          <PanelContent>
            <div className="space-y-2">
              {models?.map((m) => (
                <div key={m.model} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[200px]">
                    {m.model.replace('anthropic:', '')}
                  </span>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{m.call_count} calls ({m.call_pct}%)</span>
                    <span className="font-mono">${Number(m.cost_usd).toFixed(2)} ({m.cost_pct}%)</span>
                  </div>
                </div>
              ))}
              {!models?.length && (
                <p className="text-xs text-muted-foreground">No data yet.</p>
              )}
            </div>
          </PanelContent>
        </Panel>

        {/* Cache Performance */}
        <Panel>
          <PanelHeader title="Cache Performance" />
          <PanelContent>
            <div className="space-y-2">
              {cache?.map((c) => (
                <div key={c.agent_name} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[180px]">{c.agent_name}</span>
                  <div className="flex items-center gap-3 text-xs">
                    <StatusPill tone={c.cache_hit_rate >= 0.6 ? 'success' : c.cache_hit_rate >= 0.3 ? 'warning' : 'danger'}>
                      {(c.cache_hit_rate * 100).toFixed(0)}% hit
                    </StatusPill>
                    <span className="text-muted-foreground">
                      w/r {c.write_to_read_ratio.toFixed(2)}
                    </span>
                  </div>
                </div>
              ))}
              {!cache?.length && (
                <p className="text-xs text-muted-foreground">No cache data yet.</p>
              )}
            </div>
          </PanelContent>
        </Panel>

        {/* Output Efficiency */}
        <Panel>
          <PanelHeader title="Output Efficiency" />
          <PanelContent>
            <div className="space-y-2">
              {efficiency?.map((e) => (
                <div key={e.agent_name} className="flex items-center justify-between text-sm">
                  <span className="truncate max-w-[180px]">{e.agent_name}</span>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-muted-foreground">{e.output_input_ratio}x</span>
                    {e.flag === 'critical' && (
                      <StatusPill tone="danger" dot={false}>
                        <AlertTriangle className="h-3 w-3" />
                        critical
                      </StatusPill>
                    )}
                    {e.flag === 'high' && (
                      <StatusPill tone="warning" dot={false}>high</StatusPill>
                    )}
                  </div>
                </div>
              ))}
              {!efficiency?.length && (
                <p className="text-xs text-muted-foreground">No data yet.</p>
              )}
            </div>
          </PanelContent>
        </Panel>
      </div>

      {/* Expensive Calls */}
      <Panel>
        <PanelHeader title="Most Expensive Calls" />
        <PanelContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b">
                  <th className="text-left py-2 font-medium">Time</th>
                  <th className="text-left py-2 font-medium">Agent</th>
                  <th className="text-left py-2 font-medium">Model</th>
                  <th className="text-right py-2 font-medium">Input</th>
                  <th className="text-right py-2 font-medium">Output</th>
                  <th className="text-right py-2 font-medium">Cache</th>
                  <th className="text-right py-2 font-medium">Cost</th>
                </tr>
              </thead>
              <tbody>
                {expensive?.map((call) => (
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
                    <td className="py-2 text-right font-mono">{fmtTokens(call.cache_read_tokens)}</td>
                    <td className="py-2 text-right font-mono">${call.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!expensive?.length && (
              <p className="text-xs text-muted-foreground py-4 text-center">No calls recorded yet.</p>
            )}
          </div>
        </PanelContent>
      </Panel>
    </div>
  )
}
