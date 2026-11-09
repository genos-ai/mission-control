/**
 * RunRowDetail — what a mission run row expands to: summary, objective,
 * tasks, digest, decisions and artifacts, plus the buttons that open the
 * Tasks, Events, Output and Cost views in the run detail panel. Events,
 * Output and Cost read the run's execution record, whose id comes from the
 * run detail response.
 */

import { ClipboardList, DollarSign, FileText, List, Package } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useExecution, useExecutionDecisions } from '@/hooks/use-executions'
import { ACTIVE_RUN_STATUSES, useMissionRun } from '@/hooks/use-mission-runs'
import type { MissionArtifact } from '@/hooks/use-mission-artifacts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MetricTile } from '@/components/ui/metric-tile'
import { Spinner } from '@/components/ui/spinner'
import { StatusIcon } from '@/components/ui/status-icon'
import type { RunDetailView } from '@/components/workspace/run-detail-panel'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'
import { fmtCost, statusLabel } from '@/lib/format'
import { formatDuration } from '@/lib/format-date'
import { styleFor, taskTone } from '@/lib/status-tone'
import { TONE_BOX } from '@/lib/tone-class'

type ViewType = RunDetailView['type']

const VIEW_BUTTONS: { type: ViewType; label: string; icon: typeof List; needsRecord: boolean }[] = [
  { type: 'run', label: 'Tasks', icon: ClipboardList, needsRecord: false },
  { type: 'events', label: 'Events', icon: List, needsRecord: true },
  { type: 'output', label: 'Output', icon: FileText, needsRecord: true },
  { type: 'cost', label: 'Cost', icon: DollarSign, needsRecord: true },
]

const NO_ARTIFACTS: MissionArtifact[] = []

export function RunRowDetail({
  missionId,
  runId,
  artifactsByExecution,
  activeDetail,
  onOpenDetail,
}: {
  missionId: string
  runId: string
  artifactsByExecution: Map<string, MissionArtifact[]>
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const { data: detail, isLoading } = useMissionRun(missionId, runId)
  const executionId = detail?.execution_record_id ?? null
  const { data: record } = useExecution(executionId ?? undefined)
  const { data: decisions } = useExecutionDecisions(executionId ?? undefined)

  if (isLoading) {
    return (
      <div className="flex justify-center border-t border-line py-4">
        <Spinner className="h-4 w-4" />
      </div>
    )
  }
  if (!detail) return null

  const { run, tasks, digest } = detail
  const artifacts = executionId ? (artifactsByExecution.get(executionId) ?? NO_ARTIFACTS) : NO_ARTIFACTS
  const base = { missionId, runId, executionId }
  const views: Record<ViewType, RunDetailView> = {
    run: { type: 'run', ...base },
    events: { type: 'events', ...base },
    output: { type: 'output', ...base, content: record?.execution_outcome_json ?? undefined },
    cost: { type: 'cost', ...base },
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line bg-raised/40 px-4 py-3">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-2">
        <MetricTile label="Cost" value={fmtCost(run.cost_usd)} />
        <MetricTile label="Duration" value={formatDuration(run.started_at, run.ended_at)} />
        <MetricTile label="Tasks" value={String(tasks.length)} />
        <MetricTile label="Iterations" value={String(run.iteration_count)} />
        {decisions && <MetricTile label="Decisions" value={String(decisions.length)} />}
        {artifacts.length > 0 && <MetricTile label="Artifacts" value={String(artifacts.length)} />}
      </div>

      {run.objective && (
        <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
          {run.objective}
        </p>
      )}

      {(run.status_reason || run.status_detail) && (
        <p className="text-xs text-subtle [overflow-wrap:anywhere]">
          {run.status_reason && statusLabel(run.status_reason)}
          {run.status_reason && run.status_detail && ' · '}
          {run.status_detail}
        </p>
      )}

      {tasks.length > 0 && (
        <div className="flex flex-col gap-1">
          {tasks.map((task) => (
            <div
              key={task.id}
              className="flex items-center justify-between gap-3 rounded-card bg-raised px-3 py-2 text-xs"
            >
              <div className="flex min-w-0 items-center gap-2">
                <StatusIcon {...styleFor(taskTone, task.status, 'task')} />
                <span className="shrink-0 font-medium">{task.agent}</span>
                <span className="truncate text-subtle" title={task.description}>
                  {task.description}
                </span>
              </div>
              <span className="shrink-0 font-mono text-subtle">{fmtCost(task.cost_usd)}</span>
            </div>
          ))}
        </div>
      )}

      {digest && (
        <div className="rounded-card bg-raised px-3 py-2 text-xs">
          <p className="text-2xs font-medium text-muted-foreground">Digest</p>
          <p className="mt-0.5 line-clamp-4 leading-relaxed [overflow-wrap:anywhere]">{digest.summary}</p>
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

      <div className="flex flex-wrap items-center gap-1.5">
        {VIEW_BUTTONS.map(({ type, label, icon: Icon, needsRecord }) => (
          <Button
            key={type}
            variant={activeDetail?.type === type ? 'default' : 'secondary'}
            size="sm"
            aria-pressed={activeDetail?.type === type}
            disabled={needsRecord && !executionId}
            onClick={() => onOpenDetail?.(views[type])}
          >
            <Icon className="h-3 w-3" />
            {label}
          </Button>
        ))}
        {executionId && ACTIVE_RUN_STATUSES.has(run.status) && (
          <Link
            to={ROUTES.MISSION_RUN_LIVE(missionId, executionId)}
            className="ml-1 rounded-chip px-1.5 text-xs text-warning transition-colors duration-150 hover:bg-warning/10"
          >
            Live
          </Link>
        )}
      </div>
    </div>
  )
}
