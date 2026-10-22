import { AlertTriangle } from 'lucide-react'
import { Panel, PanelContent, PanelHeader } from '@/components/ui/panel'
import { Progress } from '@/components/ui/progress'
import { StatusPill } from '@/components/ui/status-pill'
import { cn } from '@/lib/cn'
import { agentShortName, fmtCost, fmtTokens } from '@/lib/format'
import type { Tone } from '@/lib/status-tone'
import { TONE_BOX, TONE_TEXT } from '@/lib/tone-class'
import type { MissionCostAgent, MissionCostCache, MissionCostEfficiency } from '@/types'

// A cache hit rate at or above SUCCESS is healthy, at or above WARNING is worth a look.
const CACHE_SUCCESS_RATE = 0.5
const CACHE_WARNING_RATE = 0.3

function cacheTone(rate: number): Tone {
  if (rate >= CACHE_SUCCESS_RATE) return 'success'
  if (rate >= CACHE_WARNING_RATE) return 'warning'
  return 'danger'
}

/** Spend per agent, each bar sized against the dearest agent. */
export function CostByAgentPanel({ agents }: { agents: MissionCostAgent[] }) {
  const maxCost = Math.max(0, ...agents.map((a) => a.total_cost_usd))

  return (
    <Panel>
      <PanelHeader title="Cost by agent" />
      <PanelContent>
        {agents.map((a) => (
          <div key={a.agent_name} className="py-2.5">
            <div className="flex items-baseline gap-3 text-sm">
              <span className="min-w-0 flex-1 truncate" title={a.agent_name}>
                {agentShortName(a.agent_name)}
              </span>
              <span className="shrink-0 font-mono text-xs text-subtle">
                {a.call_count} {a.call_count === 1 ? 'call' : 'calls'}
              </span>
              <span className="w-[70px] shrink-0 text-right font-mono">{fmtCost(a.total_cost_usd)}</span>
            </div>
            <Progress
              value={maxCost > 0 ? (a.total_cost_usd / maxCost) * 100 : 0}
              label={`${agentShortName(a.agent_name)} cost relative to the highest`}
              className="mt-2"
            />
            <p className="mt-1.5 font-mono text-2xs text-subtle">
              {fmtTokens(a.input_tokens)} in · {fmtTokens(a.output_tokens)} out
            </p>
          </div>
        ))}
      </PanelContent>
    </Panel>
  )
}

/** Cache hit rate per agent, coloured by how healthy it is. */
export function CachePerformancePanel({ rows }: { rows: MissionCostCache[] }) {
  return (
    <Panel>
      <PanelHeader title="Cache performance" />
      <PanelContent>
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
                className="w-[90px] shrink-0"
              />
              <span className={cn('w-10 shrink-0 text-right font-mono text-xs', TONE_TEXT[tone])}>
                {(c.cache_hit_rate * 100).toFixed(0)}%
              </span>
            </div>
          )
        })}
        {rows.length === 0 && <p className="text-xs text-subtle">No cache data.</p>}
      </PanelContent>
    </Panel>
  )
}

/** Agents whose output outweighs their input beyond the configured thresholds; nothing when none do. */
export function OutputEfficiencyCallout({ rows }: { rows: MissionCostEfficiency[] }) {
  const flagged = rows.filter((e) => e.flag !== 'ok')
  if (flagged.length === 0) return null
  const tone: Tone = flagged.some((e) => e.flag === 'critical') ? 'danger' : 'warning'

  return (
    <div role="status" className={cn('flex gap-3 rounded-panel border px-4 py-3.5', TONE_BOX[tone])}>
      <AlertTriangle className={cn('mt-0.5 h-4 w-4 shrink-0', TONE_TEXT[tone])} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Output efficiency</p>
        <ul className="mt-1.5 flex flex-col gap-1.5">
          {flagged.map((e) => (
            <li key={e.agent_name} className="flex items-center gap-2 text-sm text-text-2">
              <span className="min-w-0 flex-1">
                <span className="font-mono" title={e.agent_name}>
                  {agentShortName(e.agent_name)}
                </span>{' '}
                writes {e.output_input_ratio}× as many tokens as it reads
              </span>
              <StatusPill tone={e.flag === 'critical' ? 'danger' : 'warning'} dot={false}>
                {e.flag}
              </StatusPill>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
