/**
 * WorkflowRunHistory — side panel listing past workflow runs.
 *
 * Shows status, cost, duration, and timestamp for each run.
 * Clicking a row triggers a replay overlay on the canvas.
 */

import { X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { formatDuration, formatUtc } from '@/lib/format-date'
import type { WorkflowRunRecord } from '@/types'

const STATUS_BADGE: Record<
  string,
  { variant: 'success' | 'destructive' | 'warning' | 'secondary'; label: string }
> = {
  COMPLETED: { variant: 'success', label: 'Completed' },
  FAILED: { variant: 'destructive', label: 'Failed' },
  RUNNING: { variant: 'warning', label: 'Running' },
  PENDING: { variant: 'secondary', label: 'Pending' },
  AWAITING_INPUT: { variant: 'warning', label: 'Awaiting' },
}

interface WorkflowRunHistoryProps {
  runs: WorkflowRunRecord[]
  isLoading: boolean
  selectedRunId: string | null
  onSelectRun: (runId: string) => void
  onClose: () => void
}

export function WorkflowRunHistory({
  runs,
  isLoading,
  selectedRunId,
  onSelectRun,
  onClose,
}: WorkflowRunHistoryProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-3">
        <span className="text-xs font-medium">Run History</span>
        <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={onClose}>
          <X className="h-3 w-3" />
        </Button>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[4rem_3.5rem_3.5rem_1fr] gap-1.5 border-b px-3 py-1.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>Status</span>
        <span className="text-right">Cost</span>
        <span className="text-right">Dur</span>
        <span className="text-right">When</span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner className="h-4 w-4" />
          </div>
        ) : runs.length === 0 ? (
          <p className="px-3 py-6 text-center text-[10px] text-muted-foreground/60">
            No runs yet.
          </p>
        ) : (
          runs.map((run) => {
            const badge = STATUS_BADGE[run.status] ?? STATUS_BADGE.PENDING
            const isSelected = selectedRunId === run.id
            return (
              <button
                key={run.id}
                onClick={() => onSelectRun(run.id)}
                className={[
                  'grid w-full grid-cols-[4rem_3.5rem_3.5rem_1fr] items-center gap-1.5 border-b px-3 py-2 text-left text-[11px] transition-colors last:border-b-0',
                  isSelected
                    ? 'bg-primary/10'
                    : 'hover:bg-muted/50',
                ].join(' ')}
              >
                <span>
                  <Badge variant={badge.variant} className="text-[9px] h-3.5 px-1">
                    {badge.label}
                  </Badge>
                </span>
                <span className="text-right tabular-nums text-muted-foreground">
                  ${run.total_cost_usd.toFixed(4)}
                </span>
                <span className="text-right tabular-nums text-muted-foreground">
                  {formatDuration(run.started_at, run.completed_at)}
                </span>
                <span className="truncate text-right text-muted-foreground" title={run.started_at ?? undefined}>
                  {formatUtc(run.started_at)}
                </span>
              </button>
            )
          })
        )}
      </div>

      {/* Selected run detail */}
      {selectedRunId && (() => {
        const run = runs.find((r) => r.id === selectedRunId)
        if (!run) return null
        return (
          <div className="shrink-0 border-t bg-muted/20 px-3 py-2 text-[10px]">
            {run.result_summary && (
              <p className="mb-1.5 text-muted-foreground leading-relaxed line-clamp-3">
                {run.result_summary}
              </p>
            )}
            {run.error_data && (
              <p className="text-destructive leading-relaxed line-clamp-2">
                {(run.error_data as Record<string, unknown>).message as string ?? 'Error'}
              </p>
            )}
            <div className="flex items-center gap-2 text-muted-foreground/60">
              <span>v{run.workflow_version}</span>
              <span>{run.trigger_type}</span>
              <span className="font-mono">{run.id.slice(0, 8)}</span>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
