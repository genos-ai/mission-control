/**
 * WorkflowRunHistory — panel listing past workflow runs.
 *
 * Shows status, cost, duration, and timestamp for each run.
 * Clicking a row triggers a replay overlay on the canvas.
 */

import { X } from 'lucide-react'
import { StatusPill } from '@/components/ui/status-pill'
import { Button } from '@/components/ui/button'
import { PanelHeader } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { fmtCost, statusLabel } from '@/lib/format'
import { formatDuration, formatUtc } from '@/lib/format-date'
import { runTone, styleFor } from '@/lib/status-tone'
import type { RunStatus, WorkflowRunRecord } from '@/types'

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
  const selectedRun = selectedRunId ? runs.find((r) => r.id === selectedRunId) : undefined

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Run history"
        actions={
          <Button variant="ghost" size="icon-sm" aria-label="Close run history" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        }
      />

      <div className="flex-1 space-y-1.5 overflow-y-auto px-4 pb-3">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : runs.length === 0 ? (
          <p className="py-6 text-center text-xs text-subtle">No runs yet.</p>
        ) : (
          runs.map((run) => {
            const status = run.status.toLowerCase() as RunStatus
            const { tone } = styleFor(runTone, status, 'workflow run')
            return (
              <button
                key={run.id}
                onClick={() => onSelectRun(run.id)}
                className={
                  selectedRunId === run.id
                    ? 'flex w-full flex-col gap-1.5 rounded-card bg-brand/10 px-3 py-2 text-left text-xs transition-colors'
                    : 'flex w-full flex-col gap-1.5 rounded-card bg-raised px-3 py-2 text-left text-xs transition-colors hover:bg-raised-2'
                }
              >
                <span className="flex items-center justify-between gap-2">
                  <StatusPill tone={tone} pulse={status === 'running'}>
                    {statusLabel(status)}
                  </StatusPill>
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {fmtCost(run.total_cost_usd)}
                  </span>
                </span>
                <span className="flex items-center justify-between gap-2 text-subtle">
                  <span title={run.started_at ?? undefined}>{formatUtc(run.started_at)}</span>
                  <span className="tabular-nums">{formatDuration(run.started_at, run.completed_at)}</span>
                </span>
              </button>
            )
          })
        )}
      </div>

      {selectedRun && (
        <div className="shrink-0 space-y-1.5 border-t border-line px-4 py-3 text-xs">
          {selectedRun.result_summary && (
            <p className="line-clamp-3 leading-relaxed text-muted-foreground">
              {selectedRun.result_summary}
            </p>
          )}
          {selectedRun.error_data && (
            <p className="line-clamp-2 leading-relaxed text-danger">
              {(selectedRun.error_data as Record<string, unknown>).message as string ?? 'Error'}
            </p>
          )}
          <div className="flex items-center gap-2 text-subtle">
            <span>v{selectedRun.workflow_version}</span>
            <span>{selectedRun.trigger_type}</span>
            <span className="font-mono">{selectedRun.id.slice(0, 8)}</span>
          </div>
        </div>
      )}
    </div>
  )
}
