/**
 * LiveSummary — the panel across the top of a live run: what it is, its
 * elapsed time, cost and step count, the panel toggles and Cancel run.
 * Replaces the old header bar and footer.
 */

import { Activity, ListChecks, Radio, StopCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { StatusPill } from '@/components/ui/status-pill'
import { useNow } from '@/hooks/use-now'
import { cn } from '@/lib/cn'
import { fmtCost, fmtTokens, statusLabel } from '@/lib/format'
import { formatElapsed, parseUtc } from '@/lib/format-date'
import { runTone, styleFor } from '@/lib/status-tone'
import { TONE_DOT } from '@/lib/tone-class'
import { useLiveRunStore } from '@/stores/live-run'
import type { ExecutionRecordDetail } from '@/types'

export function LiveSummary({
  execution,
  inFlight,
  connected,
  activityOpen,
  resultsOpen,
  onToggleActivity,
  onToggleResults,
  onCancel,
  cancelling,
}: {
  execution: ExecutionRecordDetail
  inFlight: boolean
  connected: boolean
  activityOpen: boolean
  resultsOpen: boolean
  onToggleActivity: () => void
  onToggleResults: () => void
  onCancel: () => void
  cancelling: boolean
}) {
  const liveCost = useLiveRunStore((s) => s.totalCost)
  const liveCompleted = useLiveRunStore((s) => s.completedTasks)
  const liveTotal = useLiveRunStore((s) => s.totalTasks)

  const { tone } = styleFor(runTone, execution.status, 'run')
  const now = useNow(inFlight)

  const startedMs = parseUtc(execution.started_at ?? execution.created_at).getTime()
  const endMs = execution.completed_at ? parseUtc(execution.completed_at).getTime() : now

  // Cost and finished steps only ever go up, and each source can lag the other: the
  // stream misses what happened before this page opened, the polled record trails it.
  const cost = Math.max(liveCost, execution.total_cost_usd)
  const tokens = recordedTokens(execution.execution_outcome_json)
  // A task execution is only recorded once it has finished.
  const finishedSteps = Math.max(liveCompleted, execution.task_executions.length)

  return (
    <Panel className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 px-[18px] py-2.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className={cn(
            'h-2 w-2 shrink-0 rounded-full',
            TONE_DOT[tone],
            inFlight && 'animate-pulse-dot motion-reduce:animate-none',
          )}
        />
        <span className="max-w-[420px] truncate text-md font-medium" title={execution.objective_statement ?? undefined}>
          {execution.objective_statement || 'Run'}
        </span>
        <span className="font-mono text-xs text-subtle">{execution.id.slice(0, 8)}</span>
      </div>

      <Stat label="Elapsed" value={formatElapsed(Math.max(0, endMs - startedMs))} />
      <Stat label="Cost" value={fmtCost(cost)} />
      {tokens && <Stat label="Tokens" value={`${fmtTokens(tokens.input)} in · ${fmtTokens(tokens.output)} out`} />}
      <Stat label="Steps" value={liveTotal > 0 ? `${finishedSteps} / ${liveTotal}` : String(finishedSteps)} />

      <div className="ml-auto flex items-center gap-2">
        {connected && inFlight ? (
          <StatusPill tone="success" pulse>
            <Radio className="h-3 w-3" />
            Live
          </StatusPill>
        ) : (
          !inFlight && <StatusPill tone={tone}>{statusLabel(execution.status)}</StatusPill>
        )}
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Activity panel"
          aria-pressed={activityOpen}
          title={activityOpen ? 'Hide activity' : 'Show activity'}
          className={cn(activityOpen && 'bg-raised text-foreground')}
          onClick={onToggleActivity}
        >
          <Activity className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Results panel"
          aria-pressed={resultsOpen}
          title={resultsOpen ? 'Hide results' : 'Show results'}
          className={cn(resultsOpen && 'bg-raised text-foreground')}
          onClick={onToggleResults}
        >
          <ListChecks className="h-3.5 w-3.5" />
        </Button>
        {inFlight && (
          <Button variant="destructive" onClick={onCancel} disabled={cancelling}>
            <StopCircle className="h-[13px] w-[13px]" />
            {cancelling ? 'Cancelling…' : 'Cancel run'}
          </Button>
        )}
      </div>
    </Panel>
  )
}

/**
 * Token counts from the run's recorded outcome. A run that has not finished, or finished
 * without recording them, has none; they are never estimated.
 */
function recordedTokens(outcome: ExecutionRecordDetail['execution_outcome_json']): { input: number; output: number } | null {
  const total = outcome?.total_tokens
  if (typeof total !== 'object' || total === null) return null
  const { input, output } = total as Record<string, unknown>
  return typeof input === 'number' && typeof output === 'number' ? { input, output } : null
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-xs text-subtle">{label}</span>
      <span className="font-mono text-base font-medium">{value}</span>
    </div>
  )
}
