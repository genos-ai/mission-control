/**
 * RunRowDetail — what a run row expands to: summary, objective, tasks,
 * decisions and artifacts, plus the buttons that open the Events, Output and
 * Cost views in the run detail panel.
 */

import { DollarSign, FileText, List, Package } from 'lucide-react'
import { useExecution, useExecutionDecisions } from '@/hooks/use-executions'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MetricTile } from '@/components/ui/metric-tile'
import { Spinner } from '@/components/ui/spinner'
import { StatusIcon } from '@/components/ui/status-icon'
import type { RunDetailView } from '@/components/workspace/run-detail-panel'
import { cn } from '@/lib/cn'
import { fmtCost } from '@/lib/format'
import { formatDuration } from '@/lib/format-date'
import { styleFor, taskTone } from '@/lib/status-tone'
import { TONE_BOX } from '@/lib/tone-class'

type ViewType = RunDetailView['type']

const VIEW_BUTTONS: { type: ViewType; label: string; icon: typeof List }[] = [
  { type: 'events', label: 'Events', icon: List },
  { type: 'output', label: 'Output', icon: FileText },
  { type: 'cost', label: 'Cost', icon: DollarSign },
]

export function RunRowDetail({
  executionId,
  artifacts,
  activeDetail,
  onOpenDetail,
}: {
  executionId: string
  artifacts: MissionArtifact[]
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const { data: detail, isLoading } = useExecution(executionId)
  const { data: decisions } = useExecutionDecisions(executionId)

  if (isLoading) {
    return (
      <div className="flex justify-center border-t border-line py-4">
        <Spinner className="h-4 w-4" />
      </div>
    )
  }
  if (!detail) return null

  const views: Record<ViewType, RunDetailView> = {
    events: { type: 'events', executionId },
    output: {
      type: 'output',
      executionId,
      content: detail.execution_outcome_json ?? undefined,
    },
    cost: { type: 'cost', executionId },
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line bg-raised/40 px-4 py-3">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2">
        <MetricTile label="Cost" value={fmtCost(detail.total_cost_usd)} />
        <MetricTile label="Duration" value={formatDuration(detail.started_at, detail.completed_at)} />
        <MetricTile label="Tasks" value={String(detail.task_executions.length)} />
        <MetricTile label="Decisions" value={String(detail.decisions.length)} />
        {artifacts.length > 0 && <MetricTile label="Artifacts" value={String(artifacts.length)} />}
      </div>

      {detail.objective_statement && (
        <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
          {detail.objective_statement}
        </p>
      )}

      {detail.task_executions.length > 0 && (
        <div className="flex flex-col gap-1">
          {detail.task_executions.map((task) => {
            // Task executions end as completed / failed / skipped (TaskExecutionStatus), a
            // different set from the run's own status, so they use taskTone, not runTone.
            const style = styleFor(taskTone, task.status, 'task execution')
            return (
              <div
                key={task.id}
                className="flex items-center justify-between gap-3 rounded-card bg-raised px-3 py-2 text-xs"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <StatusIcon {...style} />
                  <span className="truncate font-medium">{task.agent_name}</span>
                </div>
                <div className="flex shrink-0 items-center gap-3 font-mono text-subtle">
                  {task.duration_seconds ? <span>{task.duration_seconds.toFixed(1)}s</span> : null}
                  <span>{fmtCost(task.cost_usd)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {decisions && decisions.length > 0 && (
        <div className="flex flex-col gap-1">
          {decisions.map((d) => (
            <div key={d.id} className="flex items-center gap-2 rounded-card bg-raised px-3 py-2 text-xs">
              <Badge variant="outline" className="shrink-0">
                {d.decision_type}
              </Badge>
              <span className="truncate text-muted-foreground" title={d.reasoning}>
                {d.reasoning}
              </span>
            </div>
          ))}
        </div>
      )}

      {artifacts.length > 0 && (
        <div className="flex flex-col gap-1">
          {artifacts.slice(0, 5).map((a) => (
            <div
              key={a.id}
              className={cn('flex items-center gap-2 rounded-card border px-3 py-2 text-xs', TONE_BOX.violet)}
            >
              <Package className="h-3 w-3 shrink-0 text-violet" />
              <span className="flex-1 truncate font-medium">{a.title}</span>
              <Badge variant="outline" className="shrink-0">
                {a.artifact_type}
              </Badge>
            </div>
          ))}
          {artifacts.length > 5 && (
            <p className="px-1 text-2xs text-subtle">+{artifacts.length - 5} more in the Artifacts tab</p>
          )}
        </div>
      )}

      <div className="flex items-center gap-1.5">
        {VIEW_BUTTONS.map(({ type, label, icon: Icon }) => (
          <Button
            key={type}
            variant={activeDetail?.type === type ? 'default' : 'secondary'}
            size="sm"
            aria-pressed={activeDetail?.type === type}
            onClick={() => onOpenDetail?.(views[type])}
          >
            <Icon className="h-3 w-3" />
            {label}
          </Button>
        ))}
      </div>
    </div>
  )
}
