/**
 * RunsPanel — a mission's runs (Plan 88 MissionRun): filter chips and a table
 * of runs by sequence. A row expands to the run's tasks, digest and execution
 * record views (RunRowDetail).
 */

import { useMemo, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, Play } from 'lucide-react'
import { ACTIVE_RUN_STATUSES, useMissionRuns } from '@/hooks/use-mission-runs'
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
import { statusLabel } from '@/lib/format'
import { formatElapsed, formatUtc, parseUtc } from '@/lib/format-date'
import { missionRunTone, styleFor } from '@/lib/status-tone'
import { TONE_TEXT } from '@/lib/tone-class'
import type { MissionRunResponse, MissionRunStatus } from '@/types'

const RUN_LIST_LIMIT = 50

const FILTERS: { key: string; label: string; statuses: MissionRunStatus[] | undefined }[] = [
  { key: 'all', label: 'All', statuses: undefined },
  { key: 'running', label: 'Running', statuses: ['pending', 'running', 'awaiting_gate', 'paused'] },
  { key: 'succeeded', label: 'Succeeded', statuses: ['succeeded'] },
  { key: 'failed', label: 'Failed', statuses: ['failed', 'budget_stopped', 'cancelled'] },
  { key: 'skipped', label: 'Skipped/Missed', statuses: ['skipped', 'missed'] },
]

// #sequence · Status · Trigger · Objective · Scheduled for · Started · Duration
const ROW_GRID =
  'grid grid-cols-[64px_120px_76px_minmax(120px,1fr)_110px_110px_70px] items-center gap-3 px-4'

export function RunsPanel({
  missionId,
  onStartRun,
  activeDetail,
  onOpenDetail,
}: {
  missionId: string
  onStartRun?: (runId: string) => void
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('all')
  const active = FILTERS.find((f) => f.key === filter) ?? FILTERS[0]
  const { data, isLoading } = useMissionRuns(missionId, {
    statuses: active.statuses,
    limit: RUN_LIST_LIMIT,
  })
  // Pull the mission-wide artifact list once so each row can read its own artifacts
  // without a fetch. The hook is invalidated by SSE (mission.artifact.found) at the
  // layout level, so new artifacts appear live.
  const { data: allArtifacts = [] } = useMissionArtifacts(missionId)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showRunModal, setShowRunModal] = useState(false)

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

  const runs = data?.runs ?? []

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <FilterChip key={f.key} active={filter === f.key} onClick={() => setFilter(f.key)}>
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
      ) : runs.length === 0 && filter === 'all' ? (
        <Panel>
          <EmptyState
            title="No runs yet"
            description="A run is one execution of this mission, started by hand, by the Director or by a schedule."
            action={{ label: 'New run', onClick: () => setShowRunModal(true) }}
          />
        </Panel>
      ) : (
        <Panel className="overflow-x-auto">
          <div className="min-w-[760px]">
            <div className={cn(ROW_GRID, 'py-2.5 text-2xs text-subtle')}>
              <span>Run</span>
              <span>Status</span>
              <span>Trigger</span>
              <span>Objective</span>
              <span>Scheduled for</span>
              <span>Started</span>
              <span className="text-right">Duration</span>
            </div>
            {runs.length === 0 ? (
              <p className="border-t border-line px-4 py-6 text-center text-sm text-subtle">
                No {active.label.toLowerCase()} runs.
              </p>
            ) : (
              runs.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  missionId={missionId}
                  artifactsByExecution={artifactsByExecution}
                  expanded={expandedId === run.id}
                  onToggle={() => setExpandedId(expandedId === run.id ? null : run.id)}
                  activeDetail={activeDetail?.runId === run.id ? activeDetail : null}
                  onOpenDetail={onOpenDetail}
                />
              ))
            )}
          </div>
        </Panel>
      )}

      {data?.next_before_sequence != null && (
        <p className="px-1 text-xs text-subtle">Showing the latest {runs.length} runs.</p>
      )}

      {showRunModal && (
        <RunModal
          missionId={missionId}
          onClose={() => setShowRunModal(false)}
          onStarted={(runId) => {
            setShowRunModal(false)
            if (onStartRun) {
              onStartRun(runId)
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
  run,
  missionId,
  artifactsByExecution,
  expanded,
  onToggle,
  activeDetail,
  onOpenDetail,
}: {
  run: MissionRunResponse
  missionId: string
  artifactsByExecution: Map<string, MissionArtifact[]>
  expanded: boolean
  onToggle: () => void
  activeDetail?: RunDetailView | null
  onOpenDetail?: (view: RunDetailView) => void
}) {
  const style = styleFor(missionRunTone, run.status, 'mission run')

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
        <span className="flex items-center gap-1 font-mono text-text-3">
          <ChevronRight
            className={cn('h-3 w-3 shrink-0 text-subtle transition-transform duration-150', expanded && 'rotate-90')}
          />
          #{run.sequence}
        </span>
        <span
          className={cn('flex items-center gap-1.5', TONE_TEXT[style.tone])}
          title={run.status_reason ? statusLabel(run.status_reason) : undefined}
        >
          <StatusIcon {...style} />
          {statusLabel(run.status)}
        </span>
        <span className="truncate text-muted-foreground">{statusLabel(run.trigger)}</span>
        <span className="truncate" title={run.objective ?? undefined}>
          {run.objective || <span className="text-subtle">—</span>}
        </span>
        <span className="truncate text-muted-foreground" title={run.scheduled_for ?? undefined}>
          {formatUtc(run.scheduled_for)}
        </span>
        <span className="truncate text-muted-foreground" title={run.started_at ?? undefined}>
          {formatUtc(run.started_at)}
        </span>
        <RunDuration run={run} />
      </div>

      {expanded && (
        <RunRowDetail
          missionId={missionId}
          runId={run.id}
          artifactsByExecution={artifactsByExecution}
          activeDetail={activeDetail}
          onOpenDetail={onOpenDetail}
        />
      )}
    </div>
  )
}

/** Time from start to end, or a running clock while the run is active. */
function RunDuration({ run }: { run: MissionRunResponse }) {
  const live = ACTIVE_RUN_STATUSES.has(run.status) && !run.ended_at
  const now = useNow(live && !!run.started_at)
  const end = run.ended_at ? parseUtc(run.ended_at).getTime() : live ? now : null
  const ms = run.started_at && end !== null ? end - parseUtc(run.started_at).getTime() : null

  return (
    <span className="text-right font-mono text-muted-foreground">
      {ms !== null && ms >= 0 ? formatElapsed(ms) : '—'}
    </span>
  )
}
