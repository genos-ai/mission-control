import { AlertTriangle } from 'lucide-react'
import type { ReactNode } from 'react'

import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Progress } from '@/components/ui/progress'
import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import { agentShortName, fmtUsd } from '@/lib/format'
import type { Tone } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'
import type { CachePerformance, ModelDistribution, OutputEfficiency } from '@/types'

// A cache hit rate at or above SUCCESS is healthy, at or above WARNING is worth a look.
const CACHE_SUCCESS_RATE = 0.6
const CACHE_WARNING_RATE = 0.3

function cacheTone(rate: number): Tone {
  if (rate >= CACHE_SUCCESS_RATE) return 'success'
  if (rate >= CACHE_WARNING_RATE) return 'warning'
  return 'danger'
}

/** A titled panel that says so when it has nothing to list. */
export function TokenPanel({ title, empty, children }: { title: string; empty?: string; children?: ReactNode }) {
  return (
    <Panel>
      <PanelHeader title={title} />
      <PanelContent>{empty ? <p className="text-xs text-subtle">{empty}</p> : children}</PanelContent>
    </Panel>
  )
}

/** Calls and spend per model; the bar is the model's share of cost as the API reports it. */
export function ModelDistributionPanel({ models }: { models: ModelDistribution[] }) {
  return (
    <TokenPanel title="Model distribution" empty={models.length === 0 ? 'No data yet.' : undefined}>
      {models.map((m) => {
        const name = m.model.replace('anthropic:', '')
        return (
          <div key={m.model} className="py-2.5">
            <div className="flex items-baseline gap-3 text-sm">
              <span className="min-w-0 flex-1 truncate font-mono text-xs" title={m.model}>
                {name}
              </span>
              <span className="shrink-0 text-right font-mono text-xs">
                {fmtUsd(Number(m.cost_usd))} ({m.cost_pct}%)
              </span>
            </div>
            <Progress value={Number(m.cost_pct)} label={`${name} share of cost`} className="mt-2" />
            <p className="mt-1.5 font-mono text-2xs text-subtle">
              {m.call_count} calls ({m.call_pct}%)
            </p>
          </div>
        )
      })}
    </TokenPanel>
  )
}

/** Cache hit rate and write-to-read ratio per agent, coloured by how healthy the hit rate is. */
export function TokenCachePanel({ rows }: { rows: CachePerformance[] }) {
  return (
    <TokenPanel title="Cache performance" empty={rows.length === 0 ? 'No cache data yet.' : undefined}>
      {rows.map((c) => {
        const tone = cacheTone(c.cache_hit_rate)
        return (
          <div key={c.agent_name} className="flex items-center gap-3 py-1.5 text-sm">
            <span className="min-w-0 flex-1 truncate" title={c.agent_name}>
              {agentShortName(c.agent_name)}
            </span>
            <Progress
              value={c.cache_hit_rate * 100}
              tone={tone}
              label={`${agentShortName(c.agent_name)} cache hit rate`}
              className="w-[56px] shrink-0"
            />
            <span className={cn('w-10 shrink-0 text-right font-mono text-xs', TONE_TEXT[tone])}>
              {(c.cache_hit_rate * 100).toFixed(0)}%
            </span>
            <span className="w-[60px] shrink-0 text-right font-mono text-xs text-subtle">
              w/r {c.write_to_read_ratio.toFixed(2)}
            </span>
          </div>
        )
      })}
    </TokenPanel>
  )
}

/** Output-to-input ratio per agent, with a pill for the ones the API flags. */
export function TokenEfficiencyPanel({ rows }: { rows: OutputEfficiency[] }) {
  return (
    <TokenPanel title="Output efficiency" empty={rows.length === 0 ? 'No data yet.' : undefined}>
      {rows.map((e) => (
        <div key={e.agent_name} className="flex items-center gap-3 py-1.5 text-sm">
          <span className="min-w-0 flex-1 truncate" title={e.agent_name}>
            {agentShortName(e.agent_name)}
          </span>
          {e.flag === 'critical' && (
            <StatusPill tone="danger" dot={false}>
              <AlertTriangle className="h-3 w-3" />
              critical
            </StatusPill>
          )}
          {e.flag === 'high' && (
            <StatusPill tone="warning" dot={false}>
              high
            </StatusPill>
          )}
          <span className="w-12 shrink-0 text-right font-mono text-xs text-subtle">{e.output_input_ratio}x</span>
        </div>
      ))}
    </TokenPanel>
  )
}
