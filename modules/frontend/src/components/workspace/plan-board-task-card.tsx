/**
 * PlanBoard — TaskCard, AddTaskForm, ShimmerCard, and IconButton components.
 */

import { useEffect, useRef, useState, type RefCallback } from 'react'
import {
  Loader2,
  CheckCircle2,
  XCircle,
  RotateCcw,
  StopCircle,
  Check,
  X,
  Sparkles,
  Circle,
  Clock,
  Lock,
  Wrench,
  ChevronDown,
  ChevronRight,
  MoreVertical,
  GitBranch,
  Copy,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import {
  useApproveTask,
  useRejectTask,
  useRetryTask,
  useAddPlanTask,
  type PlanTaskStatus,
} from '@/hooks/use-mission-plan'
import { useTeam } from '@/hooks/use-team'
import { useVetoCountdown } from '@/hooks/use-veto-countdown'
import { useWorkspaceStore } from '@/stores/workspace'
import type { AnnotatedTask } from './plan-board-types'
import { getBorderClass, getAgentBadgeClass } from './plan-board-types'

// ── StatusIcon ────────────────────────────────────────────────────────────

export function StatusIcon({ status }: { status: PlanTaskStatus }) {
  switch (status) {
    case 'proposed':
      return <Circle className="h-3 w-3 shrink-0 text-muted-foreground/50" />
    case 'approved':
      return <Circle className="h-3 w-3 shrink-0 fill-primary/40 text-primary" />
    case 'queued':
      return <Circle className="h-3 w-3 shrink-0 fill-amber-500/30 text-amber-500" />
    case 'running':
      return <Loader2 className="h-3 w-3 shrink-0 animate-spin text-amber-400" />
    case 'completed':
      return <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
    case 'failed':
      return <XCircle className="h-3 w-3 shrink-0 text-destructive" />
    case 'skipped':
      return <Circle className="h-3 w-3 shrink-0 text-muted-foreground/30" />
    case 'cancelled':
      return <X className="h-3 w-3 shrink-0 text-muted-foreground/40" />
    default:
      return <Circle className="h-3 w-3 shrink-0 text-muted-foreground/30" />
  }
}

// ── IconButton ────────────────────────────────────────────────────────────

export function IconButton({
  icon,
  title,
  onClick,
  disabled,
  tone,
}: {
  icon: React.ReactNode
  title: string
  onClick: () => void
  disabled?: boolean
  tone: 'emerald' | 'destructive' | 'amber' | 'muted'
}) {
  const toneClass =
    tone === 'emerald'
      ? 'text-emerald-400 hover:bg-emerald-500/10'
      : tone === 'destructive'
        ? 'text-destructive hover:bg-destructive/10'
        : tone === 'amber'
          ? 'text-amber-400 hover:bg-amber-500/10'
          : 'text-muted-foreground hover:bg-accent'

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        'rounded-md p-1 transition-colors disabled:opacity-40',
        toneClass,
      )}
    >
      {icon}
    </button>
  )
}

// ── Task card ─────────────────────────────────────────────────────────────

export function TaskCard({
  row,
  missionId,
  cardRef,
  onSelect,
}: {
  row: AnnotatedTask
  missionId: string
  cardRef: RefCallback<HTMLDivElement>
  onSelect?: (taskId: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const approve = useApproveTask(missionId)
  const reject = useRejectTask(missionId)
  const retry = useRetryTask(missionId)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  const { task, effectiveStatus, blocked, blockingDeps } = row
  const isWorkflow = task.agent.startsWith('workflow:')
  const workflowName = isWorkflow ? task.agent.slice(9) : null
  const agentShort = isWorkflow
    ? workflowName!
    : task.agent.endsWith('.agent')
      ? task.agent.slice(0, -6)
      : task.agent

  // Live tool call for this task's agent, only when running. Zustand
  // selector returns a single string so re-renders stay scoped to the
  // card whose agent's tool actually changed.
  const currentTool = useWorkspaceStore((s) =>
    effectiveStatus === 'running' ? s.agentStatuses[task.agent]?.currentTool ?? null : null,
  )

  // Plan 42 §4.4: live countdown for the ai_assisted auto-approval veto
  // window. Only meaningful when the task is currently approved AND was
  // auto-approved by the Director (has a veto_expires_at timestamp).
  const veto = useVetoCountdown(task.veto_expires_at)
  const inVetoWindow =
    effectiveStatus === 'approved' && veto !== null && !veto.expired

  async function handleApprove() {
    try {
      const result = await approve.mutateAsync(task.id)
      if (result.transitioned_task_ids.length > 1) {
        toast.success(
          `Approved ${result.transitioned_task_ids.length} tasks (dependencies included)`,
        )
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Approve failed')
    }
  }

  async function handleReject() {
    try {
      const result = await reject.mutateAsync(task.id)
      if (result.transitioned_task_ids.length > 1) {
        toast.success(
          `Cancelled ${result.transitioned_task_ids.length} tasks (dependents included)`,
        )
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Reject failed')
    }
  }

  async function handleRetry() {
    try {
      await retry.mutateAsync(task.id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Retry failed')
    }
  }

  const borderClass = getBorderClass(effectiveStatus)
  const dimmed =
    blocked ||
    effectiveStatus === 'cancelled' ||
    effectiveStatus === 'skipped'
  const clickable =
    onSelect && (effectiveStatus === 'failed' || effectiveStatus === 'completed')

  return (
    <div
      ref={cardRef}
      onClick={clickable ? () => onSelect(task.id) : undefined}
      className={cn(
        'relative rounded-md border bg-card shadow-sm p-2.5 text-xs transition-colors animate-card-enter',
        borderClass,
        dimmed && 'opacity-60',
        clickable && 'cursor-pointer hover:ring-1 hover:ring-inset hover:ring-primary/30',
      )}
    >

      {/* Header: domain-colored agent badge + blocked pill + veto + status + menu */}
      <div className="mb-1.5 flex items-center gap-1.5">
        <span
          className={cn(
            'inline-flex max-w-[120px] items-center gap-1 truncate rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider',
            isWorkflow
              ? 'bg-violet-500/10 text-violet-400 ring-1 ring-inset ring-violet-500/30'
              : getAgentBadgeClass(effectiveStatus, task.agent),
          )}
          title={task.agent}
        >
          {isWorkflow && <GitBranch className="h-2.5 w-2.5 shrink-0" />}
          {agentShort}
        </span>
        {blocked && (
          <span
            className="flex items-center gap-0.5 text-[9px] text-muted-foreground/60"
            title={`Blocked by: ${blockingDeps.join(', ')}`}
          >
            <Lock className="h-2.5 w-2.5" />
            blocked
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {inVetoWindow && veto && (
            <span
              className="flex items-center gap-0.5 rounded bg-amber-500/10 px-1 py-0.5 text-[9px] text-amber-400"
              title="Auto-approved by the Director — click X to veto before expiry"
            >
              <Clock className="h-2.5 w-2.5" />
              {veto.remainingSec}s
            </span>
          )}
          <StatusIcon status={effectiveStatus} />
          {/* ⋮ card menu */}
          <div ref={menuRef} className="relative">
            <button
              onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v) }}
              className="rounded p-0.5 text-muted-foreground/25 hover:text-muted-foreground/70 hover:bg-accent"
              title="More actions"
            >
              <MoreVertical className="h-3 w-3" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-5 z-50 min-w-[130px] rounded-md border bg-popover shadow-md py-0.5 text-[11px]">
                {(effectiveStatus === 'proposed' || effectiveStatus === 'approved' || effectiveStatus === 'queued') && (
                  <button
                    onClick={() => { setMenuOpen(false); handleReject() }}
                    disabled={reject.isPending}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-destructive hover:bg-accent disabled:opacity-40"
                  >
                    <X className="h-3 w-3" />
                    {effectiveStatus === 'proposed' ? 'Reject' : 'Cancel'}
                  </button>
                )}
                {effectiveStatus === 'failed' && (
                  <button
                    onClick={() => { setMenuOpen(false); handleRetry() }}
                    disabled={retry.isPending}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-accent disabled:opacity-40"
                  >
                    <RotateCcw className="h-3 w-3" />
                    Retry
                  </button>
                )}
                <div className="mx-2 my-0.5 border-t border-border/50" />
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(task.id)
                    toast.success(`Copied ${task.id}`)
                    setMenuOpen(false)
                  }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-muted-foreground hover:bg-accent"
                >
                  <Copy className="h-3 w-3" />
                  Copy task ID
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Task ID + Description */}
      <button
        onClick={(e) => {
          e.stopPropagation()
          navigator.clipboard.writeText(task.id)
          toast.success(`Copied ${task.id}`)
        }}
        className="mb-0.5 font-mono text-[9px] text-muted-foreground/40 hover:text-muted-foreground/70 cursor-copy"
        title="Click to copy task ID"
      >
        {task.id.slice(0, 8)}…
      </button>
      <p className="text-[12px] leading-snug">
        {task.description || task.id}
      </p>

      {/* Live tool indicator on running cards */}
      {currentTool && (
        <div className="mt-1 flex items-center gap-1 text-[10px] text-amber-400/80">
          <Wrench className="h-2.5 w-2.5 shrink-0" />
          <span className="truncate">{currentTool}</span>
        </div>
      )}

      {/* Meta line: cost/duration (terminal only) + retries + dep count. */}
      {(() => {
        const terminal =
          effectiveStatus === 'completed' || effectiveStatus === 'failed'
        const showMetrics =
          terminal &&
          (task.cost_usd > 0 || task.duration_seconds > 0)
        const hasMeta =
          showMetrics ||
          task.retry_count > 0 ||
          task.dependencies.length > 0
        if (!hasMeta) return null
        return (
          <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground/60">
            {showMetrics && (
              <span className="tabular-nums" title="Cost · duration">
                ${task.cost_usd.toFixed(4)} · {task.duration_seconds.toFixed(1)}s
              </span>
            )}
            {task.retry_count > 0 && (
              <span className="text-amber-400/70">
                {task.retry_count} {task.retry_count === 1 ? 'retry' : 'retries'}
              </span>
            )}
            {task.dependencies.length > 0 && (
              <span title={`Depends on: ${task.dependencies.join(', ')}`}>
                {task.dependencies.length} dep
                {task.dependencies.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
        )
      })()}

      {/* Result / failure preview */}
      {task.result_summary && effectiveStatus === 'completed' && (
        <>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 flex items-center gap-0.5 text-[10px] text-muted-foreground/50 hover:text-muted-foreground/80"
          >
            {expanded ? (
              <ChevronDown className="h-2.5 w-2.5" />
            ) : (
              <ChevronRight className="h-2.5 w-2.5" />
            )}
            {expanded ? 'hide result' : 'show result'}
          </button>
          {expanded && (
            <div className="mt-1.5 border-t border-border/50 pt-1.5">
              <MarkdownRenderer
                content={task.result_summary}
                className="text-[11px]"
              />
            </div>
          )}
        </>
      )}

      {task.failure_reason && effectiveStatus === 'failed' && (
        <p className="mt-1.5 line-clamp-2 text-[10px] text-destructive/70">
          {task.failure_reason}
        </p>
      )}

      {/* Actions footer */}
      <div className="mt-1.5 flex items-center justify-end gap-1">
        {effectiveStatus === 'proposed' && (
          <>
            <IconButton
              icon={<Check className="h-3 w-3" />}
              title="Approve (with transitive dependencies)"
              onClick={handleApprove}
              disabled={approve.isPending}
              tone="emerald"
            />
            <IconButton
              icon={<X className="h-3 w-3" />}
              title="Reject (with transitive dependents)"
              onClick={handleReject}
              disabled={reject.isPending}
              tone="destructive"
            />
          </>
        )}
        {(effectiveStatus === 'approved' || effectiveStatus === 'queued') && (
          <IconButton
            icon={<X className="h-3 w-3" />}
            title={
              inVetoWindow
                ? `Veto this auto-approval (${veto?.remainingSec ?? 0}s remaining)`
                : 'Unapprove (reject)'
            }
            onClick={handleReject}
            disabled={reject.isPending}
            tone={inVetoWindow ? 'amber' : 'muted'}
          />
        )}
        {effectiveStatus === 'running' && (
          <IconButton
            icon={<StopCircle className="h-3 w-3" />}
            title="Stop this task"
            onClick={handleReject}
            disabled={reject.isPending}
            tone="destructive"
          />
        )}
        {effectiveStatus === 'failed' && (
          <IconButton
            icon={<RotateCcw className="h-3 w-3" />}
            title="Retry this task"
            onClick={handleRetry}
            disabled={retry.isPending}
            tone="amber"
          />
        )}
      </div>

      {/* Indeterminate progress bar for running cards */}
      {effectiveStatus === 'running' && (
        <div className="mt-2 h-[2px] w-full overflow-hidden rounded-full bg-amber-500/15">
          <div className="h-full w-1/2 animate-pulse rounded-full bg-amber-400/60" />
        </div>
      )}
    </div>
  )
}

// ── Shimmer placeholder (refining) ───────────────────────────────────────

export function ShimmerCard() {
  return (
    <div className="rounded-md border border-primary/30 bg-card shadow-sm p-2.5">
      <div className="flex items-center gap-1.5">
        <Sparkles className="h-3 w-3 animate-pulse text-primary/60" />
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Refining plan…
        </span>
      </div>
      <div className="mt-2 space-y-1">
        <div className="h-2 w-4/5 animate-pulse rounded bg-muted" />
        <div className="h-2 w-3/5 animate-pulse rounded bg-muted" />
      </div>
    </div>
  )
}

// ── Add task inline form ─────────────────────────────────────────────────

export function AddTaskForm({
  missionId,
  onDone,
}: {
  missionId: string
  onDone: () => void
}) {
  const [description, setDescription] = useState('')
  const [agentInput, setAgentInput] = useState('')
  const addTask = useAddPlanTask(missionId)
  const { data: team } = useTeam(missionId)

  const agentNames = (team ?? [])
    .filter((m) => m.enabled && m.agent?.agent_name)
    .map((m) => m.agent!.agent_name)

  async function handleSubmit() {
    const desc = description.trim()
    const agent = agentInput.trim()
    if (!desc || !agent) return
    try {
      await addTask.mutateAsync({ description: desc, agent })
      onDone()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add task')
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { onDone(); return }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
  }

  return (
    <div className="mt-1.5 rounded-lg border bg-card p-2.5 space-y-2 shadow-sm">
      <Textarea
        autoFocus
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Task description…"
        rows={2}
        className="resize-none text-[12px]"
        disabled={addTask.isPending}
      />
      {agentNames.length > 0 ? (
        <select
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          disabled={addTask.isPending}
          className="w-full rounded border bg-transparent px-2 py-1 text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <option value="">Select agent…</option>
          {agentNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      ) : (
        <input
          value={agentInput}
          onChange={(e) => setAgentInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Agent name (e.g. code.agent)"
          className="w-full rounded border bg-transparent px-2 py-1 text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          disabled={addTask.isPending}
        />
      )}
      <div className="flex items-center justify-end gap-1.5">
        <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={onDone} disabled={addTask.isPending}>
          Cancel
        </Button>
        <Button
          size="sm"
          className="h-6 px-3 text-[11px]"
          onClick={handleSubmit}
          disabled={addTask.isPending || !description.trim() || !agentInput.trim()}
        >
          {addTask.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : 'Add task'}
        </Button>
      </div>
    </div>
  )
}
