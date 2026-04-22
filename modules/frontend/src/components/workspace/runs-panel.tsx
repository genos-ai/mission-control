/**
 * RunsPanel — full-panel execution history for a mission, rendered as a
 * feed mode inside the workspace center panel. Lists past and in-flight
 * runs with expandable detail (cost, duration, task executions, decisions,
 * event log / output / cost detail drawer triggers).
 */

import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Play,
  ChevronDown,
  ChevronRight,
  FileText,
  DollarSign,
  List,
  Package,
  Radio,
  StopCircle,
} from 'lucide-react'
import { formatUtc } from '@/lib/format-date'
import toast from 'react-hot-toast'
import {
  useExecutions,
  useExecution,
  useExecutionDecisions,
  useCancelExecution,
} from '@/hooks/use-executions'
import {
  useMissionArtifacts,
  type MissionArtifact,
} from '@/hooks/use-mission-artifacts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { RunModal } from '@/components/mission/run-modal'
import { ROUTES } from '@/lib/constants'
import type { RunDetailView } from '@/components/workspace/run-detail-panel'
import type { ExecutionRecord } from '@/types'

const STATUS_BADGE: Record<
  string,
  { variant: 'success' | 'destructive' | 'warning' | 'secondary'; label: string }
> = {
  completed: { variant: 'success', label: 'Completed' },
  failed: { variant: 'destructive', label: 'Failed' },
  running: { variant: 'warning', label: 'Running' },
  pending: { variant: 'secondary', label: 'Pending' },
  cancelled: { variant: 'secondary', label: 'Cancelled' },
}

// ---------------------------------------------------------------------------

export function RunsPanel({
  missionId,
  onStartRun,
  activeDetail,
  onOpenDetail,
}: {
  missionId: string
  onStartRun?: (executionId: string) => void
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const navigate = useNavigate()
  const { data, isLoading } = useExecutions({ limit: 50, mission_id: missionId })
  // Plan 43: pull the mission-wide artifact list once so per-row
  // rendering can filter client-side without a per-row fetch. The
  // hook is SSE-invalidated on mission.artifact.found at the layout
  // level, so new artifacts appear live without manual refresh.
  const { data: allArtifacts = [] } = useMissionArtifacts(missionId)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showRunModal, setShowRunModal] = useState(false)

  const executions = useMemo(
    () =>
      [...(data?.executions ?? [])].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [data?.executions],
  )

  // Group artifacts by execution_record_id once so HistoryRow and
  // HistoryDetail can read a row's artifacts in O(1).
  const artifactsByExecution = useMemo(() => {
    const map = new Map<string, MissionArtifact[]>()
    for (const a of allArtifacts) {
      if (!a.execution_record_id) continue
      const bucket = map.get(a.execution_record_id)
      if (bucket) {
        bucket.push(a)
      } else {
        map.set(a.execution_record_id, [a])
      }
    }
    return map
  }, [allArtifacts])

  return (
    <div className="flex flex-1 min-w-0 h-full flex-col">
      {/* Status bar — run count + New Run action */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b px-4">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          {data?.total != null ? `${data.total} total` : 'Runs'}
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-5 gap-1 px-2 text-[11px]"
          onClick={() => setShowRunModal(true)}
        >
          <Play className="h-3 w-3" />
          New Run
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : executions.length === 0 ? (
          <p className="px-4 py-8 text-xs text-muted-foreground/60 text-center">
            No runs yet.
          </p>
        ) : (
          <div>
            {/* Column headers */}
            <div className="grid grid-cols-[1.5rem_1fr_5rem_4rem_7.5rem] gap-2 border-b px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              <span />
              <span>Session</span>
              <span>Status</span>
              <span className="text-right">Cost</span>
              <span className="text-right">When</span>
            </div>
            {executions.map((exec) => (
              <HistoryRow
                key={exec.id}
                execution={exec}
                missionId={missionId}
                artifacts={artifactsByExecution.get(exec.id) ?? []}
                expanded={expandedId === exec.id}
                onToggle={() =>
                  setExpandedId(expandedId === exec.id ? null : exec.id)
                }
                onNavigateLive={() =>
                  navigate(ROUTES.MISSION_RUN_LIVE(missionId, exec.id))
                }
                activeDetail={activeDetail?.executionId === exec.id ? activeDetail : null}
                onOpenDetail={onOpenDetail}
              />
            ))}
          </div>
        )}
      </div>

      {showRunModal && (
        <RunModal
          missionId={missionId}
          onClose={() => setShowRunModal(false)}
          onStarted={() => {
            setShowRunModal(false)
            if (onStartRun) {
              onStartRun('')
            } else {
              navigate(ROUTES.MISSION_PLAN(missionId))
            }
          }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function HistoryRow({
  execution,
  missionId: _missionId,
  artifacts,
  expanded,
  onToggle,
  onNavigateLive,
  activeDetail,
  onOpenDetail,
}: {
  execution: ExecutionRecord
  missionId: string
  artifacts: MissionArtifact[]
  expanded: boolean
  onToggle: () => void
  onNavigateLive: () => void
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const badge = STATUS_BADGE[execution.status] ?? STATUS_BADGE.pending
  const isRunning =
    execution.status === 'running' || execution.status === 'pending'

  // Plan 46 Phase 2 #3: duration from the list-row timestamps (no
  // extra detail fetch needed). Null for runs that haven't started
  // or completed yet — MetricsSubLine just drops the pill.
  const durationSec =
    execution.started_at && execution.completed_at
      ? (new Date(execution.completed_at).getTime() -
          new Date(execution.started_at).getTime()) /
        1000
      : null

  return (
    <div className="border-b last:border-b-0">
      <div className="grid grid-cols-[1.5rem_1fr_5rem_4rem_7.5rem] items-center gap-2 px-4 py-2.5 text-xs">
        <button onClick={onToggle} className="flex items-center text-muted-foreground">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </button>

        <div className="flex min-w-0 flex-col gap-0.5">
          <button
            onClick={isRunning ? onNavigateLive : onToggle}
            className="flex items-center gap-1.5 truncate text-left"
          >
            <span className="truncate font-mono text-[10px] text-muted-foreground">
              {execution.id.slice(0, 8)}
            </span>
            {isRunning && (
              <Badge variant="warning" className="text-[9px] h-3.5 px-1">
                <Radio className="mr-0.5 h-2 w-2 animate-pulse" />
                Live
              </Badge>
            )}
          </button>
          {/* Plan 46 Phase 2 #3 metrics sub-line: task count ·
              duration · artifact count, each hidden when zero so a
              live run with no output yet renders a clean single
              line. Promotes what used to be expand-only info to the
              always-visible row. */}
          <MetricsSubLine
            taskCount={execution.task_count ?? 0}
            durationSec={durationSec}
            artifactCount={artifacts.length}
          />
        </div>

        <span className="flex items-center">
          <Badge variant={badge.variant} className="text-[9px] h-3.5 px-1">
            {badge.label}
          </Badge>
        </span>

        <span className="flex items-center justify-end text-muted-foreground">
          ${execution.total_cost_usd.toFixed(4)}
        </span>

        <span className="flex items-center justify-end gap-1.5 text-muted-foreground">
          <span className="truncate" title={execution.created_at}>
            {execution.created_at
              ? formatUtc(execution.created_at)
              : '—'}
          </span>
          {isRunning && <CancelButton executionId={execution.id} />}
        </span>
      </div>

      {expanded && (
        <HistoryDetail
          executionId={execution.id}
          artifacts={artifacts}
          activeDetail={activeDetail}
          onOpenDetail={onOpenDetail}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function MetricsSubLine({
  taskCount,
  durationSec,
  artifactCount,
}: {
  taskCount: number
  durationSec: number | null
  artifactCount: number
}) {
  const parts: string[] = []
  if (taskCount > 0) {
    parts.push(`${taskCount} task${taskCount === 1 ? '' : 's'}`)
  }
  if (durationSec !== null) {
    parts.push(`${durationSec.toFixed(1)}s`)
  }
  if (artifactCount > 0) {
    parts.push(`${artifactCount} artifact${artifactCount === 1 ? '' : 's'}`)
  }
  if (parts.length === 0) return null
  return (
    <span className="truncate text-[10px] text-muted-foreground/60">
      {parts.join(' · ')}
    </span>
  )
}

// ---------------------------------------------------------------------------

function CancelButton({ executionId }: { executionId: string }) {
  const cancel = useCancelExecution()
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        cancel.mutate(executionId, {
          onSuccess: () => toast.success('Cancelled'),
          onError: (err) => toast.error(err.message),
        })
      }}
      disabled={cancel.isPending}
      className="shrink-0 text-destructive hover:text-destructive/80"
      title="Cancel run"
    >
      <StopCircle className="h-3 w-3" />
    </button>
  )
}

// ---------------------------------------------------------------------------

function HistoryDetail({
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
      <div className="flex justify-center py-4">
        <Spinner className="h-4 w-4" />
      </div>
    )
  }
  if (!detail) return null

  const duration =
    detail.started_at && detail.completed_at
      ? (
          (new Date(detail.completed_at).getTime() -
            new Date(detail.started_at).getTime()) /
          1000
        ).toFixed(1)
      : null

  return (
    <div className="border-t bg-muted/20 px-4 py-3">
      {/* Summary pills */}
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        <span className="rounded border px-2 py-0.5">
          <span className="text-muted-foreground">cost </span>
          ${detail.total_cost_usd.toFixed(4)}
        </span>
        {duration && (
          <span className="rounded border px-2 py-0.5">
            <span className="text-muted-foreground">dur </span>
            {duration}s
          </span>
        )}
        <span className="rounded border px-2 py-0.5">
          <span className="text-muted-foreground">tasks </span>
          {detail.task_executions.length}
        </span>
        <span className="rounded border px-2 py-0.5">
          <span className="text-muted-foreground">decisions </span>
          {detail.decisions.length}
        </span>
        {artifacts.length > 0 && (
          <span className="rounded border border-violet-500/30 px-2 py-0.5 text-violet-400">
            <Package className="mr-1 inline h-2.5 w-2.5" />
            {artifacts.length} artifact{artifacts.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Objective */}
      {detail.objective_statement && (
        <p className="mb-3 text-xs text-muted-foreground leading-relaxed line-clamp-3">
          {detail.objective_statement}
        </p>
      )}

      {/* Task list */}
      {detail.task_executions.length > 0 && (
        <div className="mb-3 space-y-1">
          {detail.task_executions.map((task) => {
            const tb = STATUS_BADGE[task.status] ?? STATUS_BADGE.pending
            return (
              <div
                key={task.id}
                className="flex items-center justify-between rounded border px-2.5 py-1.5 text-xs"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant={tb.variant} className="text-[9px] h-3.5 px-1 shrink-0">
                    {tb.label}
                  </Badge>
                  <span className="truncate font-medium">{task.agent_name}</span>
                </div>
                <div className="flex items-center gap-2 text-muted-foreground shrink-0">
                  {task.duration_seconds && (
                    <span>{task.duration_seconds.toFixed(1)}s</span>
                  )}
                  <span>${task.cost_usd.toFixed(4)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Decisions */}
      {decisions && decisions.length > 0 && (
        <div className="mb-3 space-y-1">
          {decisions.map((d) => (
            <div
              key={d.id}
              className="flex items-center gap-2 rounded border px-2.5 py-1.5 text-xs"
            >
              <Badge variant="outline" className="text-[9px] h-3.5 px-1 shrink-0">
                {d.decision_type}
              </Badge>
              <span className="truncate text-muted-foreground">{d.reasoning}</span>
            </div>
          ))}
        </div>
      )}

      {/* Artifacts */}
      {artifacts.length > 0 && (
        <div className="mb-3 space-y-1">
          {artifacts.slice(0, 5).map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-2 rounded border border-violet-500/20 bg-violet-500/5 px-2.5 py-1.5 text-xs"
            >
              <Package className="h-3 w-3 shrink-0 text-violet-400" />
              <span className="flex-1 truncate font-medium">{a.title}</span>
              <Badge variant="outline" className="h-3.5 text-[9px] shrink-0">
                {a.artifact_type}
              </Badge>
            </div>
          ))}
          {artifacts.length > 5 && (
            <p className="px-1 text-[10px] text-muted-foreground/60">
              +{artifacts.length - 5} more in Artifacts tab
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-1.5">
        {(
          [
            { type: 'events', icon: <List className="mr-1 h-2.5 w-2.5" />, label: 'Events', view: { type: 'events' as const, executionId } },
            { type: 'output', icon: <FileText className="mr-1 h-2.5 w-2.5" />, label: 'Output', view: { type: 'output' as const, executionId, content: detail.execution_outcome_json as Record<string, unknown> | undefined } },
            { type: 'cost', icon: <DollarSign className="mr-1 h-2.5 w-2.5" />, label: 'Cost', view: { type: 'cost' as const, executionId } },
          ] as const
        ).map(({ type, icon, label, view }) => (
          <Button
            key={type}
            variant={activeDetail?.type === type ? 'secondary' : 'outline'}
            size="sm"
            className="h-6 px-2 text-[10px]"
            onClick={() => onOpenDetail?.(view)}
          >
            {icon}
            {label}
          </Button>
        ))}
      </div>
    </div>
  )
}
