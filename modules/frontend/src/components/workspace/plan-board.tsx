/**
 * PlanBoard — long-lived mission backlog (Plan 42).
 *
 * Reads the persistent plan from the backend (GET /missions/:id/plan),
 * joins `task_plan_json.tasks[]` (bodies) with `task_states[]` (status)
 * keyed by string task_id, and overlays in-flight status from
 * `workspaceStore.liveTaskOverlay` populated by plan.step.* SSE events.
 *
 * Tasks are grouped into four sections (Proposed / Approved / Running /
 * Done). Each row has inline actions driven by its state:
 *   proposed   → Approve / Reject
 *   approved   → (nothing, waits for dispatch)
 *   running    → (read-only, live indicator)
 *   failed     → Retry
 *
 * Top bar shows:
 *   - Version indicator (vN)
 *   - Gate-mode selector (Plan 42 §10.4)
 *   - Cumulative budget bar (Plan 42 §10.7)
 *   - "Run N approved" button (calls /plan/dispatch)
 *   - "Refine" button (inline prompt → /plan/refine)
 *
 * Empty state: prominent CTA to chat with the Director.
 */

import { useState } from 'react'
import {
  Loader2,
  CheckCircle2,
  XCircle,
  RotateCcw,
  Check,
  X,
  Play,
  Sparkles,
  Brain,
  FileText,
  Circle,
  AlertTriangle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import {
  useMissionPlan,
  useRefinePlan,
  useApproveTask,
  useRejectTask,
  useRetryTask,
  useDispatchApproved,
  useUpdatePlan,
  type MissionPlan,
  type PlanTaskBody,
  type PlanTaskState,
  type PlanTaskStatus,
  type GateMode,
} from '@/hooks/use-mission-plan'
import { useWorkspaceStore } from '@/stores/workspace'

// ── Joined view + section grouping ───────────────────────────────────────

/** One row in the UI — task body + persistent state + live overlay. */
interface JoinedTask {
  body: PlanTaskBody
  state: PlanTaskState | null
  /** Live overlay status wins when present (in-flight from SSE). */
  effectiveStatus: PlanTaskStatus
}

type Section = 'proposed' | 'approved' | 'running' | 'done'

const SECTION_STATUSES: Record<Section, PlanTaskStatus[]> = {
  proposed: ['proposed'],
  approved: ['approved', 'queued'],
  running: ['running'],
  done: ['completed', 'failed', 'skipped', 'cancelled'],
}

const SECTION_LABELS: Record<Section, string> = {
  proposed: 'Proposed',
  approved: 'Approved',
  running: 'Running',
  done: 'Done',
}

// ── Board root ───────────────────────────────────────────────────────────

export function PlanBoard({ missionId }: { missionId: string }) {
  const { data: plan, isLoading, error } = useMissionPlan(missionId)
  const liveOverlay = useWorkspaceStore((s) => s.liveTaskOverlay)
  const setFeedMode = useWorkspaceStore((s) => s.setFeedMode)

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-5 w-5" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8">
        <AlertTriangle className="h-6 w-6 text-destructive/60" />
        <p className="text-sm text-destructive/80">Failed to load plan</p>
        <p className="text-xs text-muted-foreground/60">{String(error)}</p>
      </div>
    )
  }

  if (!plan) return null

  const tasks = plan.task_plan_json?.tasks ?? []

  // Empty state — no refinement has happened yet
  if (tasks.length === 0) {
    return <EmptyState onChat={() => setFeedMode('chat')} plan={plan} />
  }

  // Join bodies ⋈ states ⋈ liveOverlay by task_id
  const statesById: Record<string, PlanTaskState> = {}
  for (const s of plan.task_states) statesById[s.task_id] = s

  const joined: JoinedTask[] = tasks.map((body) => {
    const state = statesById[body.task_id] ?? null
    const overlay = liveOverlay[body.task_id]
    // Overlay wins over durable state when present — in-flight status.
    const effective: PlanTaskStatus =
      (overlay?.status as PlanTaskStatus) ??
      (state?.status as PlanTaskStatus) ??
      'proposed'
    return { body, state, effectiveStatus: effective }
  })

  return (
    <PlanBoardInner
      plan={plan}
      missionId={missionId}
      joined={joined}
    />
  )
}

function PlanBoardInner({
  plan,
  missionId,
  joined,
}: {
  plan: MissionPlan
  missionId: string
  joined: JoinedTask[]
}) {
  const [refineOpen, setRefineOpen] = useState(false)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PlanTopBar
        plan={plan}
        missionId={missionId}
        joined={joined}
        onToggleRefine={() => setRefineOpen((v) => !v)}
        refineOpen={refineOpen}
      />
      {refineOpen && (
        <RefinePanel
          missionId={missionId}
          onDone={() => setRefineOpen(false)}
        />
      )}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-5 p-4">
          {(Object.keys(SECTION_STATUSES) as Section[]).map((section) => {
            const rows = joined.filter((j) =>
              SECTION_STATUSES[section].includes(j.effectiveStatus),
            )
            // Sort done section so newest is last (most recent first)
            const sorted =
              section === 'done'
                ? [...rows].sort((a, b) =>
                    (b.state?.last_attempt_at ?? '').localeCompare(
                      a.state?.last_attempt_at ?? '',
                    ),
                  )
                : rows
            return (
              <TaskSection
                key={section}
                section={section}
                rows={sorted}
                missionId={missionId}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Top bar ──────────────────────────────────────────────────────────────

function PlanTopBar({
  plan,
  missionId,
  joined,
  onToggleRefine,
  refineOpen,
}: {
  plan: MissionPlan
  missionId: string
  joined: JoinedTask[]
  onToggleRefine: () => void
  refineOpen: boolean
}) {
  const updatePlan = useUpdatePlan(missionId)
  const dispatch = useDispatchApproved(missionId)

  const approvedCount = joined.filter(
    (j) => j.effectiveStatus === 'approved',
  ).length

  const budgetPct =
    plan.budget_usd_ceiling && plan.budget_usd_ceiling > 0
      ? Math.min(100, (plan.total_spent_usd / plan.budget_usd_ceiling) * 100)
      : 0

  async function handleGateMode(mode: GateMode) {
    try {
      await updatePlan.mutateAsync({ gate_mode: mode })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update gate mode')
    }
  }

  async function handleDispatch() {
    try {
      const result = await dispatch.mutateAsync()
      toast.success(
        `Run ${result.outcome_status} — $${result.total_cost_usd.toFixed(4)}`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Dispatch failed')
    }
  }

  return (
    <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Plan
      </span>
      <Badge variant="secondary" className="text-[9px] h-4">v{plan.version}</Badge>

      <div className="relative">
        <select
          value={plan.gate_mode ?? 'interactive'}
          onChange={(e) => handleGateMode(e.target.value as GateMode)}
          disabled={updatePlan.isPending}
          className="h-6 appearance-none rounded border bg-transparent pl-2 pr-6 text-[10px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          title="Autonomy mode (Plan 42 §10.4)"
        >
          <option value="off">off — fully autonomous</option>
          <option value="interactive">interactive — human in loop</option>
          <option value="ai_assisted">ai_assisted — AI in loop</option>
          <option value="autonomous">autonomous — unattended</option>
        </select>
      </div>

      {plan.budget_usd_ceiling != null && plan.budget_usd_ceiling > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground tabular-nums">
            ${plan.total_spent_usd.toFixed(2)} / ${plan.budget_usd_ceiling.toFixed(2)}
          </span>
          <div className="h-1.5 w-20 rounded-full bg-muted overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full transition-all',
                budgetPct > 80 ? 'bg-destructive' :
                budgetPct > 50 ? 'bg-amber-500' :
                'bg-emerald-500',
              )}
              style={{ width: `${budgetPct}%` }}
            />
          </div>
        </div>
      )}

      <div className="ml-auto flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          className={cn(
            'h-6 gap-1 px-2 text-[11px]',
            refineOpen && 'bg-accent text-foreground',
          )}
          onClick={onToggleRefine}
          title="Refine plan via Planning Agent"
        >
          <Sparkles className="h-3 w-3" />
          Refine
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 gap-1 px-2 text-[11px]"
          onClick={handleDispatch}
          disabled={dispatch.isPending || approvedCount === 0}
          title={
            approvedCount === 0
              ? 'Approve tasks before running'
              : `Run ${approvedCount} approved task${approvedCount === 1 ? '' : 's'}`
          }
        >
          {dispatch.isPending
            ? <Loader2 className="h-3 w-3 animate-spin" />
            : <Play className="h-3 w-3" />}
          Run {approvedCount > 0 ? approvedCount : ''}
        </Button>
      </div>
    </div>
  )
}

// ── Refine panel (inline) ────────────────────────────────────────────────

function RefinePanel({
  missionId,
  onDone,
}: {
  missionId: string
  onDone: () => void
}) {
  const [instructions, setInstructions] = useState('')
  const refine = useRefinePlan(missionId)

  async function handleSubmit() {
    const trimmed = instructions.trim()
    if (!trimmed) return
    try {
      await refine.mutateAsync(trimmed)
      toast.success('Plan refined')
      setInstructions('')
      onDone()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refinement failed')
    }
  }

  return (
    <div className="shrink-0 border-b bg-muted/30 p-3">
      <div className="mx-auto max-w-3xl space-y-2">
        <p className="text-[11px] text-muted-foreground">
          Describe the plan you want. The Planning Agent will produce a
          new TaskPlan based on the mission brief + your instructions.
          task_ids are preserved for unchanged tasks so approvals and run
          history survive.
        </p>
        <Textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. Split the code-quality audit into two tasks: one for style, one for security. Add a final task that summarises findings."
          rows={3}
          className="resize-none text-[12px]"
          disabled={refine.isPending}
        />
        <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-[11px]"
            onClick={onDone}
            disabled={refine.isPending}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            className="h-6 gap-1 px-3 text-[11px]"
            onClick={handleSubmit}
            disabled={refine.isPending || !instructions.trim()}
          >
            {refine.isPending
              ? <Loader2 className="h-3 w-3 animate-spin" />
              : <Sparkles className="h-3 w-3" />}
            {refine.isPending ? 'Refining…' : 'Refine plan'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────

function EmptyState({
  onChat,
  plan,
}: {
  onChat: () => void
  plan: MissionPlan
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
        <FileText className="h-7 w-7 text-primary/60" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">No plan yet</p>
        <p className="max-w-[360px] text-xs text-muted-foreground/70">
          Ask the Director what you want to work on — they'll propose a plan
          you can review and approve here.
        </p>
      </div>
      <Button size="sm" onClick={onChat} className="gap-1.5">
        <Brain className="h-3.5 w-3.5" />
        Talk to the Director
      </Button>
      {plan.gate_mode && (
        <p className="text-[10px] text-muted-foreground/40">
          Plan v{plan.version} · gate_mode: {plan.gate_mode}
        </p>
      )}
    </div>
  )
}

// ── Section ──────────────────────────────────────────────────────────────

function TaskSection({
  section,
  rows,
  missionId,
}: {
  section: Section
  rows: JoinedTask[]
  missionId: string
}) {
  if (rows.length === 0) return null

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2 px-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {SECTION_LABELS[section]}
        </span>
        <Badge variant="secondary" className="h-4 px-1.5 text-[9px]">
          {rows.length}
        </Badge>
      </div>
      <div className="space-y-1.5">
        {rows.map((row) => (
          <TaskRow key={row.body.task_id} row={row} missionId={missionId} />
        ))}
      </div>
    </div>
  )
}

// ── Task row ─────────────────────────────────────────────────────────────

function TaskRow({
  row,
  missionId,
}: {
  row: JoinedTask
  missionId: string
}) {
  const [expanded, setExpanded] = useState(false)
  const approve = useApproveTask(missionId)
  const reject = useRejectTask(missionId)
  const retry = useRetryTask(missionId)

  const { body, state, effectiveStatus } = row
  const agentShort = body.agent.endsWith('.agent')
    ? body.agent.slice(0, -6)
    : body.agent

  const statusStyles = getStatusStyles(effectiveStatus)

  async function handleApprove() {
    try {
      const result = await approve.mutateAsync(body.task_id)
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
      const result = await reject.mutateAsync(body.task_id)
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
      await retry.mutateAsync(body.task_id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Retry failed')
    }
  }

  return (
    <div
      className={cn(
        'rounded-md border bg-card px-3 py-2 text-xs transition-colors',
        statusStyles.border,
      )}
    >
      <div className="flex items-start gap-2">
        <StatusIcon status={effectiveStatus} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="flex-1 truncate text-[13px] leading-snug">
              {body.description || body.task_id}
            </p>
          </div>
          <div className="mt-0.5 flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground/60">
              └ {agentShort}
            </span>
            {state && state.retry_count > 0 && (
              <span className="text-[10px] text-amber-400/70">
                · {state.retry_count} {state.retry_count === 1 ? 'retry' : 'retries'}
              </span>
            )}
            {body.dependencies.length > 0 && (
              <span
                className="text-[10px] text-muted-foreground/40"
                title={`Depends on: ${body.dependencies.join(', ')}`}
              >
                · {body.dependencies.length} dep{body.dependencies.length > 1 ? 's' : ''}
              </span>
            )}
          </div>

          {state?.result_summary && effectiveStatus === 'completed' && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-[10px] text-muted-foreground/50 hover:text-muted-foreground/80"
            >
              {expanded ? 'hide result' : 'show result'}
            </button>
          )}
          {expanded && state?.result_summary && (
            <div className="mt-1 border-t border-border/50 pt-1.5">
              <MarkdownRenderer content={state.result_summary} className="text-[11px]" />
            </div>
          )}

          {state?.failure_reason && effectiveStatus === 'failed' && (
            <p className="mt-1 text-[10px] text-destructive/70 line-clamp-2">
              {state.failure_reason}
            </p>
          )}
        </div>

        {/* Inline actions */}
        <div className="flex shrink-0 items-center gap-1">
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
          {effectiveStatus === 'approved' && (
            <IconButton
              icon={<X className="h-3 w-3" />}
              title="Unapprove (reject)"
              onClick={handleReject}
              disabled={reject.isPending}
              tone="muted"
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
      </div>
    </div>
  )
}

// ── Presentation helpers ─────────────────────────────────────────────────

function StatusIcon({ status }: { status: PlanTaskStatus }) {
  switch (status) {
    case 'proposed':
      return <Circle className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/50" />
    case 'approved':
      return <Circle className="mt-0.5 h-3 w-3 shrink-0 fill-primary/40 text-primary" />
    case 'queued':
      return <Circle className="mt-0.5 h-3 w-3 shrink-0 fill-amber-500/30 text-amber-500" />
    case 'running':
      return <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin text-amber-400" />
    case 'completed':
      return <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />
    case 'failed':
      return <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-destructive" />
    case 'skipped':
      return <Circle className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/30" />
    case 'cancelled':
      return <X className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/40" />
    default:
      return <Circle className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/30" />
  }
}

function getStatusStyles(status: PlanTaskStatus): { border: string } {
  switch (status) {
    case 'running':
      return { border: 'border-amber-500/40' }
    case 'completed':
      return { border: 'border-emerald-500/25' }
    case 'failed':
      return { border: 'border-destructive/40' }
    case 'cancelled':
    case 'skipped':
      return { border: 'border-border/30 opacity-60' }
    case 'approved':
    case 'queued':
      return { border: 'border-primary/30' }
    default:
      return { border: 'border-border' }
  }
}

function IconButton({
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
    tone === 'emerald' ? 'text-emerald-400 hover:bg-emerald-500/10' :
    tone === 'destructive' ? 'text-destructive hover:bg-destructive/10' :
    tone === 'amber' ? 'text-amber-400 hover:bg-amber-500/10' :
    'text-muted-foreground hover:bg-accent'

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
