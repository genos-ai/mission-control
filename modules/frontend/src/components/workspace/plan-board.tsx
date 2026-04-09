/**
 * PlanBoard — 4-column kanban board driven by WorkspaceStore.
 *
 * Columns:  Planned → Running → Verifying → Done
 *
 * Cards move between columns as SSE events arrive. The Planned column
 * supports drag-to-reorder (visual only for now; order affects dispatch
 * priority in a future phase).
 */

import { useState } from 'react'
import {
  Loader2,
  Zap,
  CheckCircle,
  XCircle,
  RotateCcw,
  Package,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { useWorkspaceStore, type PlanTask } from '@/stores/workspace'
import { IdleOverview } from './idle-overview'

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

interface Column {
  id: 'planned' | 'running' | 'verifying' | 'done'
  label: string
  statuses: PlanTask['status'][]
}

const COLUMNS: Column[] = [
  { id: 'planned',   label: 'Planned',   statuses: ['pending'] },
  { id: 'running',   label: 'Running',   statuses: ['running'] },
  { id: 'verifying', label: 'Verifying', statuses: ['verifying'] },
  { id: 'done',      label: 'Done',      statuses: ['success', 'failed'] },
]

// ---------------------------------------------------------------------------
// Board root
// ---------------------------------------------------------------------------

export function PlanBoard({ missionId }: { missionId: string }) {
  const tasks = useWorkspaceStore((s) => s.planTasks)
  const planningPhase = useWorkspaceStore((s) => s.planningPhase)

  // Show idle overview when no run has started yet
  if (planningPhase === 'idle') {
    return <IdleOverview missionId={missionId} />
  }

  const isEmpty = tasks.length === 0

  return (
    <div className="flex h-full gap-3 overflow-x-auto p-3">
      {COLUMNS.map((col) => {
        const colTasks = tasks
          .filter((t) => col.statuses.includes(t.status))
          .sort((a, b) =>
            col.id === 'planned'
              ? a.orderIndex - b.orderIndex
              : col.id === 'done'
              ? b.orderIndex - a.orderIndex // most-recent done first
              : 0,
          )
        return (
          <PlanColumn
            key={col.id}
            column={col}
            tasks={colTasks}
            showPlaceholder={col.id === 'planned' && isEmpty && planningPhase === 'planning'}
          />
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Column
// ---------------------------------------------------------------------------

function PlanColumn({
  column,
  tasks,
  showPlaceholder,
}: {
  column: Column
  tasks: PlanTask[]
  showPlaceholder: boolean
}) {
  const runningCount = column.id === 'running' ? tasks.length : 0

  return (
    <div className="flex w-[220px] shrink-0 flex-col rounded-lg border bg-muted/20">
      {/* Header */}
      <div className="flex h-9 items-center gap-2 border-b px-3">
        <span className="flex-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {column.label}
        </span>
        {tasks.length > 0 && (
          <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
            {tasks.length}
          </Badge>
        )}
        {runningCount > 1 && (
          <Badge
            variant="outline"
            className="h-4 border-amber-500/50 px-1.5 text-[10px] text-amber-400"
          >
            ⚡ {runningCount}
          </Badge>
        )}
      </div>

      {/* Cards */}
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2">
        {showPlaceholder && <PlanningPlaceholder />}
        {tasks.map((task) => (
          <TaskCard key={task.taskId} task={task} />
        ))}
        {!showPlaceholder && tasks.length === 0 && (
          <div className="flex flex-1 items-center justify-center py-8">
            <span className="text-[10px] text-muted-foreground/40">—</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Planning placeholder — shimmer card while Planning Agent is running
// ---------------------------------------------------------------------------

function PlanningPlaceholder() {
  return (
    <div className="animate-pulse rounded-md border border-dashed border-border bg-card p-3">
      <div className="mb-2 flex items-center gap-2">
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/50" />
        <span className="text-xs text-muted-foreground/60">Assembling plan…</span>
      </div>
      <div className="space-y-1.5">
        <div className="h-2.5 w-3/4 rounded bg-muted/60" />
        <div className="h-2.5 w-1/2 rounded bg-muted/40" />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Task card
// ---------------------------------------------------------------------------

function TaskCard({ task }: { task: PlanTask }) {
  const [expanded, setExpanded] = useState(false)

  const isRunning = task.status === 'running'
  const isVerifying = task.status === 'verifying'
  const isFailed = task.status === 'failed'
  const isSuccess = task.status === 'success'
  const isDone = isSuccess || isFailed

  const borderColor =
    isFailed    ? 'border-destructive/40' :
    isRunning   ? 'border-amber-500/40' :
    isVerifying ? 'border-blue-500/40' :
    isSuccess   ? 'border-emerald-500/30' :
    'border-border'

  const agentShort = task.agentName.endsWith('.agent')
    ? task.agentName.slice(0, -6)
    : task.agentName

  return (
    <div className={cn('rounded-md border bg-card p-2.5 text-xs', borderColor)}>
      {/* Agent badge + status icon */}
      <div className="mb-1.5 flex items-center gap-1.5">
        <Badge
          variant="outline"
          className={cn(
            'h-4 max-w-[140px] truncate px-1.5 text-[9px]',
            isRunning   && 'border-amber-500/50 text-amber-400',
            isVerifying && 'border-blue-500/50 text-blue-400',
            isSuccess   && 'border-emerald-500/50 text-emerald-400',
            isFailed    && 'border-destructive/50 text-destructive',
          )}
          title={task.agentName}
        >
          {agentShort}
        </Badge>
        <div className="ml-auto shrink-0">
          {isRunning && <Loader2 className="h-3 w-3 animate-spin text-amber-400" />}
          {isVerifying && <Loader2 className="h-3 w-3 animate-spin text-blue-400" />}
          {isSuccess && <CheckCircle className="h-3 w-3 text-emerald-400" />}
          {isFailed && <XCircle className="h-3 w-3 text-destructive" />}
        </div>
      </div>

      {/* Description */}
      <p className="mb-1.5 leading-snug text-foreground/90">{task.description}</p>

      {/* Live tool indicator */}
      {isRunning && task.currentTool && (
        <div className="mb-1.5 flex items-center gap-1 text-[10px] text-amber-400/80">
          <Zap className="h-2.5 w-2.5 shrink-0" />
          <span className="truncate">{task.currentTool}</span>
        </div>
      )}

      {/* Retry badge */}
      {task.retryCount > 0 && (
        <div className="mb-1.5 flex items-center gap-1 text-[10px] text-muted-foreground/70">
          <RotateCcw className="h-2.5 w-2.5" />
          <span>{task.retryCount} {task.retryCount === 1 ? 'retry' : 'retries'}</span>
        </div>
      )}

      {/* Done: cost + duration */}
      {isDone && (task.costUsd > 0 || task.durationSeconds > 0) && (
        <div className="mb-1.5 flex items-center gap-2 text-[10px] text-muted-foreground/70">
          {task.costUsd > 0 && <span>${task.costUsd.toFixed(4)}</span>}
          {task.durationSeconds > 0 && <span>{task.durationSeconds.toFixed(1)}s</span>}
          {task.artifactEmitted && (
            <span className="flex items-center gap-0.5 text-violet-400">
              <Package className="h-2.5 w-2.5" />artifact
            </span>
          )}
        </div>
      )}

      {/* Expandable result summary */}
      {isSuccess && task.resultSummary && (
        <div>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground/60 hover:text-muted-foreground"
          >
            {expanded ? <ChevronUp className="h-2.5 w-2.5" /> : <ChevronDown className="h-2.5 w-2.5" />}
            {expanded ? 'Hide result' : 'Show result'}
          </button>
          {expanded && (
            <div className="mt-1.5 border-t border-border pt-1.5">
              <MarkdownRenderer content={task.resultSummary} className="text-[10px]" />
            </div>
          )}
        </div>
      )}

      {/* Failure reason + recovery actions */}
      {isFailed && (
        <div className="mt-1.5 border-t border-destructive/20 pt-1.5">
          {task.failureReason && (
            <p className="mb-1.5 text-[10px] text-destructive/80 line-clamp-2">
              {task.failureReason}
            </p>
          )}
          <FailureActions task={task} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Failure recovery actions
// ---------------------------------------------------------------------------

function FailureActions({ task }: { task: PlanTask }) {
  // These emit to a future retry/skip API — for now they show intent
  // and will be wired to backend endpoints in Phase 4.
  return (
    <div className="flex items-center gap-1">
      <Button
        variant="outline"
        size="sm"
        className="h-5 px-1.5 text-[10px] text-amber-400 border-amber-500/40 hover:bg-amber-500/10"
        title={`Retry task ${task.taskId}`}
        onClick={() => {
          // TODO: POST /executions/{id}/retry-task {task_id}
        }}
      >
        <RotateCcw className="mr-0.5 h-2.5 w-2.5" />
        Retry
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-5 px-1.5 text-[10px] text-muted-foreground hover:text-foreground"
        title={`Skip task ${task.taskId}`}
        onClick={() => {
          // TODO: POST /executions/{id}/skip-task {task_id}
        }}
      >
        <AlertTriangle className="mr-0.5 h-2.5 w-2.5" />
        Skip
      </Button>
    </div>
  )
}
