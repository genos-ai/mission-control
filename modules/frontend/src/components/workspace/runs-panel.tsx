/**
 * RunsPanel — a mission's run history: filter chips and a table of runs.
 * A row expands to the run's tasks, decisions and artifacts (RunRowDetail).
 */

import { useMemo, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronRight, Play, StopCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { useCancelExecution, useExecutions } from '@/hooks/use-executions'
import { useMissionArtifacts, type MissionArtifact } from '@/hooks/use-mission-artifacts'
import { useNow } from '@/hooks/use-now'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { FilterChip } from '@/components/ui/filter-chip'
import { Panel } from '@/components/ui/panel'
import { Spinner } from '@/components/ui/spinner'
import { StatusIcon } from '@/components/ui/status-icon'
import { RunModal } from '@/components/mission/run-modal'
import { RunRowDetail } from '@/components/workspace/run-row-detail'
import type { RunDetailView } from '@/components/workspace/run-detail-panel'
import { cn } from '@/lib/cn'
import { ROUTES } from '@/lib/constants'
import { fmtCost, statusLabel } from '@/lib/format'
import { formatElapsed, formatUtc, parseUtc } from '@/lib/format-date'
import { runTone, styleFor } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'
import type { ExecutionRecord } from '@/types'

const IN_FLIGHT = new Set(['pending', 'running', 'awaiting_input'])

const FILTERS: { key: string; label: string; match: (status: string) => boolean }[] = [
  { key: 'all', label: 'All', match: () => true },
  { key: 'running', label: 'Running', match: (s) => IN_FLIGHT.has(s) },
  { key: 'completed', label: 'Completed', match: (s) => s === 'completed' },
  { key: 'failed', label: 'Failed', match: (s) => s === 'failed' || s === 'timed_out' },
]

// Status · Run · Objective · Started · Duration · Cost
const ROW_GRID = 'grid grid-cols-[104px_84px_minmax(120px,1fr)_118px_70px_72px] items-center gap-3 px-4'

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
  // Pull the mission-wide artifact list once so each row can read its own artifacts
  // without a fetch. The hook is invalidated by SSE (mission.artifact.found) at the
  // layout level, so new artifacts appear live.
  const { data: allArtifacts = [] } = useMissionArtifacts(missionId)
  const [filter, setFilter] = useState('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showRunModal, setShowRunModal] = useState(false)

  const executions = useMemo(
    () =>
      [...(data?.executions ?? [])].sort(
        (a, b) => parseUtc(b.created_at).getTime() - parseUtc(a.created_at).getTime(),
      ),
    [data?.executions],
  )

  const artifactsByExecution = useMemo(() => {
    const map = new Map<string, MissionArtifact[]>()
    for (const a of allArtifacts) {
      if (!a.execution_record_id) continue
      const bucket = map.get(a.execution_record_id)
      if (bucket) bucket.push(a)
      else map.set(a.execution_record_id, [a])
    }
    return map
  }, [allArtifacts])

  const active = FILTERS.find((f) => f.key === filter) ?? FILTERS[0]
  const visible = executions.filter((e) => active.match(e.status))

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <FilterChip
            key={f.key}
            active={filter === f.key}
            count={executions.filter((e) => f.match(e.status)).length}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </FilterChip>
        ))}
        <Button variant="secondary" className="ml-auto" onClick={() => setShowRunModal(true)}>
          <Play className="h-[13px] w-[13px]" />
          New run
        </Button>
      </div>

      {isLoading ? (
        <Panel className="flex justify-center py-12">
          <Spinner />
        </Panel>
      ) : executions.length === 0 ? (
        <Panel>
          <EmptyState
            title="No runs yet"
            description="A run is one execution of this mission's plan or a workflow."
            action={{ label: 'New run', onClick: () => setShowRunModal(true) }}
          />
        </Panel>
      ) : (
        <Panel className="overflow-x-auto">
          <div className="min-w-[640px]">
            <div className={cn(ROW_GRID, 'py-2.5 text-2xs text-subtle')}>
              <span>Status</span>
              <span>Run</span>
              <span>Objective</span>
              <span>Started</span>
              <span className="text-right">Duration</span>
              <span className="text-right">Cost</span>
            </div>
            {visible.length === 0 ? (
              <p className="border-t border-line px-4 py-6 text-center text-sm text-subtle">
                No {active.label.toLowerCase()} runs.
              </p>
            ) : (
              visible.map((exec) => (
                <RunRow
                  key={exec.id}
                  execution={exec}
                  missionId={missionId}
                  artifacts={artifactsByExecution.get(exec.id) ?? []}
                  expanded={expandedId === exec.id}
                  onToggle={() => setExpandedId(expandedId === exec.id ? null : exec.id)}
                  activeDetail={activeDetail?.executionId === exec.id ? activeDetail : null}
                  onOpenDetail={onOpenDetail}
                />
              ))
            )}
          </div>
        </Panel>
      )}

      {data && data.total > executions.length && (
        <p className="px-1 text-xs text-subtle">
          Showing the latest {executions.length} of {data.total} runs.
        </p>
      )}

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
    </>
  )
}

// ---------------------------------------------------------------------------

function RunRow({
  execution,
  missionId,
  artifacts,
  expanded,
  onToggle,
  activeDetail,
  onOpenDetail,
}: {
  execution: ExecutionRecord
  missionId: string
  artifacts: MissionArtifact[]
  expanded: boolean
  onToggle: () => void
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const style = styleFor(runTone, execution.status, 'run')
  const inFlight = IN_FLIGHT.has(execution.status)

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.target !== e.currentTarget) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onToggle()
    }
  }

  return (
    <div className="border-t border-line">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggle}
        onKeyDown={onKeyDown}
        className={cn(
          ROW_GRID,
          'cursor-pointer py-[11px] text-sm transition-colors duration-150 hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/40',
          expanded && 'bg-hover',
        )}
      >
        <span className={cn('flex items-center gap-1.5', TONE_TEXT[style.tone])}>
          <StatusIcon {...style} />
          {statusLabel(execution.status)}
        </span>
        <span className="flex items-center gap-1 font-mono text-text-3">
          <ChevronRight
            className={cn('h-3 w-3 shrink-0 text-subtle transition-transform duration-150', expanded && 'rotate-90')}
          />
          {execution.id.slice(0, 8)}
        </span>
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate" title={execution.objective_statement ?? undefined}>
            {execution.objective_statement || <span className="text-subtle">—</span>}
          </span>
          <RunCounts taskCount={execution.task_count} artifactCount={artifacts.length} />
          {inFlight && (
            <>
              <Link
                to={ROUTES.MISSION_RUN_LIVE(missionId, execution.id)}
                onClick={(e) => e.stopPropagation()}
                className="shrink-0 rounded-chip px-1.5 text-xs text-warning transition-colors duration-150 hover:bg-warning/10"
              >
                Live
              </Link>
              <CancelRunButton executionId={execution.id} />
            </>
          )}
        </span>
        <span className="truncate text-muted-foreground" title={execution.created_at}>
          {execution.created_at ? formatUtc(execution.created_at) : '—'}
        </span>
        <RunDuration execution={execution} />
        <span className="text-right font-mono">{fmtCost(execution.total_cost_usd)}</span>
      </div>

      {expanded && (
        <RunRowDetail executionId={execution.id} artifacts={artifacts} activeDetail={activeDetail} onOpenDetail={onOpenDetail} />
      )}
    </div>
  )
}

/** Time from start to finish, or a running clock while the run is in flight. */
function RunDuration({ execution }: { execution: ExecutionRecord }) {
  const live = IN_FLIGHT.has(execution.status) && !execution.completed_at
  const now = useNow(live && !!execution.started_at)
  const end = execution.completed_at ? parseUtc(execution.completed_at).getTime() : live ? now : null
  const ms = execution.started_at && end !== null ? end - parseUtc(execution.started_at).getTime() : null

  return (
    <span className="text-right font-mono text-muted-foreground">
      {ms !== null && ms >= 0 ? formatElapsed(ms) : '—'}
    </span>
  )
}

function RunCounts({ taskCount, artifactCount }: { taskCount: number; artifactCount: number }) {
  const parts: string[] = []
  if (taskCount > 0) parts.push(`${taskCount} task${taskCount === 1 ? '' : 's'}`)
  if (artifactCount > 0) parts.push(`${artifactCount} artifact${artifactCount === 1 ? '' : 's'}`)
  if (parts.length === 0) return null
  return <span className="shrink-0 text-2xs text-subtle">{parts.join(' · ')}</span>
}

function CancelRunButton({ executionId }: { executionId: string }) {
  const cancel = useCancelExecution()
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      className="shrink-0 hover:text-danger"
      aria-label="Cancel run"
      title="Cancel run"
      disabled={cancel.isPending}
      onClick={(e) => {
        e.stopPropagation()
        cancel.mutate(executionId, {
          onSuccess: () => toast.success('Cancelled'),
          onError: (err) => toast.error(err.message),
        })
      }}
    >
      <StopCircle className="h-3 w-3" />
    </Button>
  )
}
