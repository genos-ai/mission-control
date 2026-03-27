import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Play, ChevronDown, ChevronRight, FileText, DollarSign, List, Radio } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { useExecutions, useExecution, useExecutionDecisions } from '@/hooks/use-executions'
import { useDrawerStore } from '@/stores/drawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { EmptyState } from '@/components/ui/empty-state'
import { RunModal } from '@/components/mission/run-modal'
import { ROUTES } from '@/lib/constants'
import type { ExecutionRecord } from '@/types'

const STATUS_BADGE: Record<string, { variant: 'success' | 'destructive' | 'warning' | 'secondary'; label: string }> = {
  completed: { variant: 'success', label: 'Completed' },
  failed: { variant: 'destructive', label: 'Failed' },
  running: { variant: 'warning', label: 'Running' },
  pending: { variant: 'secondary', label: 'Pending' },
  cancelled: { variant: 'secondary', label: 'Cancelled' },
}

export default function RunsPage() {
  const { id: missionId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data, isLoading } = useExecutions({ limit: 50, mission_id: missionId })
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showRunModal, setShowRunModal] = useState(false)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner />
      </div>
    )
  }

  const executions = data?.executions ?? []

  if (executions.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<Play className="h-6 w-6 text-muted-foreground" />}
          title="No runs"
          description="No runs yet. Go to Workflows to trigger your first run."
          action={{
            label: 'Go to Workflows',
            onClick: () => navigate(`/missions/${missionId}/workflows`),
          }}
        />
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Runs</h2>
          <p className="text-sm text-muted-foreground">
            {data?.total ?? 0} total executions
          </p>
        </div>
        <Button onClick={() => setShowRunModal(true)}>
          <Play className="mr-2 h-4 w-4" />
          New Run
        </Button>
      </div>

      {showRunModal && (
        <RunModal
          missionId={missionId!}
          onClose={() => setShowRunModal(false)}
          onStarted={(execId) => {
            setShowRunModal(false)
            navigate(ROUTES.MISSION_RUN_LIVE(missionId!, execId))
          }}
        />
      )}

      {/* Table */}
      <div className="rounded-lg border">
        <div className="grid grid-cols-[2rem_1fr_6rem_5rem_5rem_8rem] gap-2 border-b px-4 py-2 text-xs font-semibold text-muted-foreground">
          <span />
          <span>Session</span>
          <span>Status</span>
          <span className="text-right">Cost</span>
          <span>Roster</span>
          <span className="text-right">When</span>
        </div>

        {executions.map((exec) => (
          <RunRow
            key={exec.id}
            execution={exec}
            expanded={expandedId === exec.id}
            onToggle={() =>
              setExpandedId(expandedId === exec.id ? null : exec.id)
            }
            missionId={missionId!}
          />
        ))}
      </div>
    </div>
  )
}

function RunRow({
  execution,
  expanded,
  onToggle,
  missionId,
}: {
  execution: ExecutionRecord
  expanded: boolean
  onToggle: () => void
  missionId: string
}) {
  const navigate = useNavigate()
  const badge = STATUS_BADGE[execution.status] ?? STATUS_BADGE.pending
  const isRunning = execution.status === 'running'

  return (
    <div className="border-b last:border-b-0">
      <div className="grid w-full grid-cols-[2rem_1fr_6rem_5rem_5rem_8rem] gap-2 px-4 py-3 text-sm">
        <button
          onClick={onToggle}
          className="flex items-center"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
        <button
          onClick={isRunning ? () => navigate(ROUTES.MISSION_RUN_LIVE(missionId, execution.id)) : onToggle}
          className="flex items-center gap-2 truncate text-left"
        >
          <span className="truncate font-mono text-xs">
            {execution.id.slice(0, 8)}
          </span>
          {isRunning && (
            <Badge variant="warning" className="text-[10px]">
              <Radio className="mr-1 h-2.5 w-2.5 animate-pulse" />
              Live
            </Badge>
          )}
        </button>
        <span className="flex items-center">
          <Badge variant={badge.variant} className="text-[10px]">
            {badge.label}
          </Badge>
        </span>
        <span className="flex items-center justify-end text-xs">
          ${execution.total_cost_usd.toFixed(4)}
        </span>
        <span className="flex items-center truncate text-xs text-muted-foreground">
          {execution.roster_name ?? '—'}
        </span>
        <span className="flex items-center justify-end text-xs text-muted-foreground">
          {execution.created_at
            ? formatDistanceToNow(new Date(execution.created_at), {
                addSuffix: true,
              })
            : '—'}
        </span>
      </div>

      {expanded && <RunDetail executionId={execution.id} />}
    </div>
  )
}

function RunDetail({ executionId }: { executionId: string }) {
  const { data: detail, isLoading } = useExecution(executionId)
  const { data: decisions } = useExecutionDecisions(executionId)
  const { open: openDrawer } = useDrawerStore()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Spinner />
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
    <div className="border-t bg-muted/30 px-4 py-4">
      {/* Summary cards */}
      <div className="mb-4 grid grid-cols-4 gap-3">
        <SummaryCard label="Cost" value={`$${detail.total_cost_usd.toFixed(4)}`} />
        <SummaryCard label="Duration" value={duration ? `${duration}s` : '—'} />
        <SummaryCard label="Tasks" value={String(detail.task_executions.length)} />
        <SummaryCard label="Decisions" value={String(detail.decisions.length)} />
      </div>

      {/* Objective */}
      {detail.objective_statement && (
        <div className="mb-4">
          <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
            Objective
          </h4>
          <p className="text-sm">{detail.objective_statement}</p>
        </div>
      )}

      {/* Task executions */}
      {detail.task_executions.length > 0 && (
        <div className="mb-4">
          <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Tasks
          </h4>
          <div className="space-y-1">
            {detail.task_executions.map((task) => {
              const taskBadge =
                STATUS_BADGE[task.status] ?? STATUS_BADGE.pending
              return (
                <div
                  key={task.id}
                  className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant={taskBadge.variant} className="text-[10px]">
                      {taskBadge.label}
                    </Badge>
                    <span className="font-medium">{task.agent_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {task.task_id}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {task.duration_seconds && (
                      <span>{task.duration_seconds.toFixed(1)}s</span>
                    )}
                    <span>${task.cost_usd.toFixed(4)}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Decisions */}
      {decisions && decisions.length > 0 && (
        <div className="mb-4">
          <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            Decisions
          </h4>
          <div className="space-y-1">
            {decisions.map((d) => (
              <div
                key={d.id}
                className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-[10px]">
                    {d.decision_type}
                  </Badge>
                  <span className="text-muted-foreground">{d.reasoning}</span>
                </div>
                {d.task_id && (
                  <span className="text-xs text-muted-foreground">
                    {d.task_id}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            openDrawer('event-log', { executionId })
          }
        >
          <List className="mr-1 h-3 w-3" />
          Event Log
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            openDrawer('output-preview', {
              executionId,
              content: detail.execution_outcome_json,
            })
          }
        >
          <FileText className="mr-1 h-3 w-3" />
          Output
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            openDrawer('cost-breakdown', { executionId })
          }
        >
          <DollarSign className="mr-1 h-3 w-3" />
          Cost Detail
        </Button>
      </div>
    </div>
  )
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border px-3 py-2">
      <p className="text-[10px] font-semibold uppercase text-muted-foreground">
        {label}
      </p>
      <p className="text-lg font-bold">{value}</p>
    </div>
  )
}
