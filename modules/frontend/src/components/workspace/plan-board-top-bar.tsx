/**
 * PlanBoard — PlanTopBar, PreRunGateModal, and RefinePanel components.
 */

import { useState } from 'react'
import {
  Loader2,
  X,
  Play,
  Pause,
  Sparkles,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  useRefinePlan,
  useDispatchApproved,
  useUpdatePlan,
  type MissionPlan,
  type GateMode,
} from '@/hooks/use-mission-plan'
import type { JoinedTask } from './plan-board-types'
import { PRE_RUN_GATE_KEY } from './plan-board-types'

// ── Top bar ──────────────────────────────────────────────────────────────

export function PlanTopBar({
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
  const [gateOpen, setGateOpen] = useState(false)

  const approvedTasks = joined.filter(
    (j) => j.effectiveStatus === 'approved' || j.effectiveStatus === 'queued',
  )
  const approvedCount = approvedTasks.length

  const budgetPct =
    plan.budget_usd_ceiling && plan.budget_usd_ceiling > 0
      ? Math.min(100, (plan.total_spent_usd / plan.budget_usd_ceiling) * 100)
      : 0

  const isPlanPaused = plan.status === 'paused'

  async function handleGateMode(mode: GateMode) {
    try {
      await updatePlan.mutateAsync({ gate_mode: mode })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update gate mode')
    }
  }

  async function handlePlanPauseToggle() {
    const next = isPlanPaused ? 'active' : 'paused'
    try {
      await updatePlan.mutateAsync({ status: next })
      toast.success(next === 'paused' ? 'Plan paused — dispatch stopped' : 'Plan resumed')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update plan status')
    }
  }

  async function doDispatch() {
    try {
      const result = await dispatch.mutateAsync()
      toast.success(
        `Run ${result.outcome_status} — $${result.total_cost_usd.toFixed(4)}`,
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Dispatch failed')
    }
  }

  function handleDispatch() {
    // Skip the gate if the user previously said "don't ask again".
    if (localStorage.getItem(PRE_RUN_GATE_KEY(missionId))) {
      void doDispatch()
    } else {
      setGateOpen(true)
    }
  }

  return (
    <>
    <div className="flex h-9 shrink-0 items-center gap-2 border-b px-3">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Plan
      </span>
      <Badge variant="secondary" className="h-4 text-[9px]">v{plan.version}</Badge>

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

      <Button
        size="sm"
        variant={isPlanPaused ? 'default' : 'ghost'}
        className={cn(
          'h-6 gap-1 px-2 text-[11px]',
          isPlanPaused && 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        )}
        onClick={handlePlanPauseToggle}
        disabled={updatePlan.isPending}
        title={isPlanPaused ? 'Resume autonomous dispatch' : 'Pause autonomous dispatch'}
      >
        {isPlanPaused ? (
          <>
            <Play className="h-3 w-3" />
            Resume
          </>
        ) : (
          <>
            <Pause className="h-3 w-3" />
            Pause
          </>
        )}
      </Button>

      {plan.budget_usd_ceiling != null && plan.budget_usd_ceiling > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] tabular-nums text-muted-foreground">
            ${plan.total_spent_usd.toFixed(2)} / ${plan.budget_usd_ceiling.toFixed(2)}
          </span>
          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                'h-full rounded-full transition-all',
                budgetPct > 80
                  ? 'bg-destructive'
                  : budgetPct > 50
                    ? 'bg-amber-500'
                    : 'bg-emerald-500',
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
          disabled={dispatch.isPending || approvedCount === 0 || isPlanPaused}
          title={
            isPlanPaused
              ? 'Resume the plan before running'
              : approvedCount === 0
                ? 'Approve tasks before running'
                : `Run ${approvedCount} approved task${approvedCount === 1 ? '' : 's'}`
          }
        >
          {dispatch.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          Run {approvedCount > 0 ? approvedCount : ''}
        </Button>
      </div>
    </div>

    {gateOpen && (
      <PreRunGateModal
        missionId={missionId}
        approvedTasks={approvedTasks}
        isPending={dispatch.isPending}
        onConfirm={(skipNextTime) => {
          setGateOpen(false)
          if (skipNextTime) {
            localStorage.setItem(PRE_RUN_GATE_KEY(missionId), '1')
          }
          void doDispatch()
        }}
        onCancel={() => setGateOpen(false)}
      />
    )}
    </>
  )
}

// ── Pre-run review gate (Plan 41 §3.5b) ──────────────────────────────────

function PreRunGateModal({
  missionId: _missionId,
  approvedTasks,
  isPending,
  onConfirm,
  onCancel,
}: {
  missionId: string
  approvedTasks: JoinedTask[]
  isPending: boolean
  onConfirm: (skipNextTime: boolean) => void
  onCancel: () => void
}) {
  const [skipNextTime, setSkipNextTime] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-sm rounded-lg border bg-card p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-semibold">Ready to run?</h3>
          <button
            onClick={onCancel}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="mb-3 text-xs text-muted-foreground">
          {approvedTasks.length} task{approvedTasks.length !== 1 ? 's' : ''} will
          be dispatched:
        </p>

        <div className="mb-4 max-h-48 space-y-1 overflow-y-auto">
          {approvedTasks.map((t) => (
            <div
              key={t.body.task_id}
              className="rounded border px-2.5 py-1.5 text-xs"
            >
              <span className="font-medium">{t.body.description || t.body.task_id}</span>
              <span className="ml-2 text-muted-foreground">{t.body.agent}</span>
            </div>
          ))}
        </div>

        <label className="mb-4 flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={skipNextTime}
            onChange={(e) => setSkipNextTime(e.target.checked)}
            className="h-3 w-3 rounded"
          />
          Don't ask again for this mission
        </label>

        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel} className="h-7 text-xs">
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => onConfirm(skipNextTime)}
            disabled={isPending}
            className="h-7 gap-1.5 text-xs"
          >
            {isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            Run {approvedTasks.length}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ── Refine panel (inline) ────────────────────────────────────────────────

export function RefinePanel({
  refine,
  onDone,
}: {
  refine: ReturnType<typeof useRefinePlan>
  onDone: () => void
}) {
  const [instructions, setInstructions] = useState('')

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
            {refine.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Sparkles className="h-3 w-3" />
            )}
            {refine.isPending ? 'Refining…' : 'Refine plan'}
          </Button>
        </div>
      </div>
    </div>
  )
}
