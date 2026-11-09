/**
 * PlanBoard — TaskCard and ShimmerCard.
 */

import { useState, type RefCallback } from 'react'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  GitBranch,
  GitMerge,
  Lock,
  MoreVertical,
  RotateCcw,
  Sparkles,
  StopCircle,
  Wrench,
  X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { agentStyle } from '@/lib/agent-tone'
import { agentShortName, fmtCost } from '@/lib/format'
import { taskTone } from '@/lib/status-tone'
import { TONE_DOT } from '@/lib/tone-class'
import { Button } from '@/components/ui/button'
import { Menu, type MenuItem } from '@/components/ui/menu'
import { StatusIcon } from '@/components/ui/status-icon'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { useApproveTask, useRejectTask, useRetryTask } from '@/hooks/use-mission-plan'
import { useWorkspaceStore } from '@/stores/workspace'
import type { AnnotatedTask } from './plan-board-types'

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
  const approve = useApproveTask(missionId)
  const reject = useRejectTask(missionId)
  const retry = useRetryTask(missionId)

  const { task, effectiveStatus, blocked, blockingDeps } = row
  const isWorkflow = task.agent.startsWith('workflow:')
  const agentLabel = isWorkflow ? task.agent.slice(9) : agentShortName(task.agent)
  const domainTone = isWorkflow ? 'violet' : agentStyle(task.agent).tone

  // Live tool call for this task's agent, only when running. Zustand
  // selector returns a single string so re-renders stay scoped to the
  // card whose agent's tool actually changed.
  const currentTool = useWorkspaceStore((s) =>
    effectiveStatus === 'running' ? s.agentStatuses[task.agent]?.currentTool ?? null : null,
  )

  async function handleApprove() {
    try {
      const result = await approve.mutateAsync(task.id)
      if (result.transitioned_task_ids.length > 1) {
        toast.success(`Approved ${result.transitioned_task_ids.length} tasks (dependencies included)`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Approve failed')
    }
  }

  async function handleReject() {
    try {
      const result = await reject.mutateAsync(task.id)
      if (result.transitioned_task_ids.length > 1) {
        toast.success(`Cancelled ${result.transitioned_task_ids.length} tasks (dependents included)`)
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

  function copyId() {
    navigator.clipboard.writeText(task.id)
    toast.success(`Copied ${task.id}`)
  }

  // Card buttons sit inside a card that opens the detail panel on click, so they must not bubble.
  const act = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation()
    fn()
  }

  const dimmed = blocked || effectiveStatus === 'cancelled' || effectiveStatus === 'skipped'
  const clickable = onSelect && (effectiveStatus === 'failed' || effectiveStatus === 'completed')
  const canCancel = effectiveStatus === 'proposed' || effectiveStatus === 'approved' || effectiveStatus === 'queued'
  const terminal = effectiveStatus === 'completed' || effectiveStatus === 'failed'
  const showMetrics = terminal && (task.cost_usd > 0 || task.duration_seconds > 0)

  const menuItems: MenuItem[] = [
    ...(canCancel
      ? [
          {
            label: effectiveStatus === 'proposed' ? 'Reject' : 'Cancel',
            icon: X,
            destructive: true,
            disabled: reject.isPending,
            onSelect: handleReject,
          },
        ]
      : []),
    ...(effectiveStatus === 'failed'
      ? [{ label: 'Retry', icon: RotateCcw, disabled: retry.isPending, onSelect: handleRetry }]
      : []),
    { label: 'Copy task ID', icon: Copy, separatorBefore: canCancel || effectiveStatus === 'failed', onSelect: copyId },
  ]

  return (
    <div
      ref={cardRef}
      onClick={clickable ? () => onSelect(task.id) : undefined}
      className={cn(
        // z-30 keeps the card above the dependency curves (z-20); an open menu lifts its card above the others.
        'group relative z-30 flex animate-card-enter flex-col gap-2.5 overflow-hidden rounded-card border bg-raised p-3 text-xs transition-colors duration-150 focus-within:z-40 hover:z-40',
        effectiveStatus === 'running' ? 'border-warning/35' : effectiveStatus === 'failed' ? 'border-danger/30' : 'border-panel-border',
        dimmed && 'opacity-60',
        clickable && 'cursor-pointer hover:border-border-hover',
      )}
    >
      <div className="flex items-center gap-1.5 text-2xs text-muted-foreground">
        <span className={cn('h-[7px] w-[7px] shrink-0 rounded-[2px]', TONE_DOT[domainTone])} />
        {isWorkflow && <GitBranch className="h-3 w-3 shrink-0 text-violet" />}
        <span className="truncate" title={task.agent}>{agentLabel}</span>
        {blocked && (
          <span className="flex items-center gap-0.5 text-subtle" title={`Blocked by: ${blockingDeps.join(', ')}`}>
            <Lock className="h-2.5 w-2.5" />
            blocked
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {(effectiveStatus === 'failed' || effectiveStatus === 'skipped' || effectiveStatus === 'cancelled') && (
            <StatusIcon {...taskTone[effectiveStatus]} />
          )}
          <Menu
            label="More actions"
            trigger={<MoreVertical className="h-3 w-3" />}
            items={menuItems}
            triggerClassName="opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 aria-expanded:opacity-100"
          />
        </div>
      </div>

      <p className="text-base text-pretty">{task.description || task.id}</p>

      {currentTool && (
        <div className="flex items-center gap-1 font-mono text-2xs text-warning">
          <Wrench className="h-2.5 w-2.5 shrink-0" />
          <span className="truncate">{currentTool}</span>
        </div>
      )}

      {task.failure_reason && effectiveStatus === 'failed' && (
        <p className="line-clamp-2 text-xs text-danger [overflow-wrap:anywhere]">{task.failure_reason}</p>
      )}

      {task.result_summary && effectiveStatus === 'completed' && (
        <div>
          <button
            onClick={act(() => setExpanded((v) => !v))}
            className="flex items-center gap-0.5 text-2xs text-subtle transition-colors duration-150 hover:text-foreground"
          >
            {expanded ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronRight className="h-2.5 w-2.5" />}
            {expanded ? 'hide result' : 'show result'}
          </button>
          {expanded && (
            <div className="mt-1.5 border-t border-border/60 pt-1.5">
              <MarkdownRenderer content={task.result_summary} className="text-xs" />
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5 font-mono text-2xs text-subtle">
        <button
          onClick={act(copyId)}
          className="cursor-copy transition-colors duration-150 hover:text-foreground"
          title="Click to copy task ID"
        >
          {task.id.slice(0, 4)}…
        </button>
        {task.dependencies.length > 0 && (
          <span className="flex items-center gap-1" title={`Depends on: ${task.dependencies.join(', ')}`}>
            <GitMerge className="h-3 w-3" />
            {task.dependencies.length} dep{task.dependencies.length > 1 ? 's' : ''}
          </span>
        )}
        {showMetrics && (
          <span className="tabular" title="Cost · duration">
            {fmtCost(task.cost_usd)} · {task.duration_seconds.toFixed(1)}s
          </span>
        )}
        {task.retry_count > 0 && (
          <span className="text-warning">
            {task.retry_count} {task.retry_count === 1 ? 'retry' : 'retries'}
          </span>
        )}

        <div className="ml-auto flex items-center gap-1.5 font-sans">
          {effectiveStatus === 'proposed' && (
            <>
              <Button
                variant="secondary"
                size="icon-sm"
                aria-label="Reject (with transitive dependents)"
                title="Reject (with transitive dependents)"
                className="hover:text-danger"
                onClick={act(handleReject)}
                disabled={reject.isPending}
              >
                <X className="h-3 w-3" />
              </Button>
              <Button
                size="sm"
                title="Approve (with transitive dependencies)"
                onClick={act(handleApprove)}
                disabled={approve.isPending}
              >
                <Check className="h-3 w-3" />
                Approve
              </Button>
            </>
          )}
          {(effectiveStatus === 'approved' || effectiveStatus === 'queued') && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Unapprove (reject)"
              title="Unapprove (reject)"
              onClick={act(handleReject)}
              disabled={reject.isPending}
            >
              <X className="h-3 w-3" />
            </Button>
          )}
          {effectiveStatus === 'running' && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Stop this task"
              title="Stop this task"
              className="hover:text-danger"
              onClick={act(handleReject)}
              disabled={reject.isPending}
            >
              <StopCircle className="h-3 w-3" />
            </Button>
          )}
          {effectiveStatus === 'failed' && (
            <Button variant="secondary" size="sm" onClick={act(handleRetry)} disabled={retry.isPending}>
              <RotateCcw className="h-3 w-3" />
              Retry
            </Button>
          )}
        </div>
      </div>

      {effectiveStatus === 'running' && (
        <div className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-warning/10">
          <div className="h-full w-2/5 animate-shimmer-x bg-warning motion-reduce:animate-none" />
        </div>
      )}
    </div>
  )
}

// ── Shimmer placeholder (refining) ───────────────────────────────────────

export function ShimmerCard() {
  return (
    <div className="rounded-card border border-brand/30 bg-raised p-3">
      <div className="flex items-center gap-1.5 text-2xs text-muted-foreground">
        <Sparkles className="h-3 w-3 animate-pulse-dot text-brand-text motion-reduce:animate-none" />
        Refining plan…
      </div>
      <div className="mt-2 space-y-1">
        <div className="h-2 w-4/5 animate-pulse-dot rounded bg-raised-2 motion-reduce:animate-none" />
        <div className="h-2 w-3/5 animate-pulse-dot rounded bg-raised-2 motion-reduce:animate-none" />
      </div>
    </div>
  )
}
