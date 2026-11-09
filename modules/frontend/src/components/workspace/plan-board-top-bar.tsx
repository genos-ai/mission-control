/**
 * PlanBoard — PlanTopBar, PreRunGateModal, and RefinePanel components.
 */

import { useState } from 'react'
import { Loader2, X, Play, Square, Sparkles, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { Progress } from '@/components/ui/progress'
import { Segmented } from '@/components/ui/segmented'
import { Textarea } from '@/components/ui/textarea'
import {
  useRefinePlan,
  useDispatchApproved,
  useUpdatePlan,
  useLastSupervisorDecision,
  type MissionPlan,
} from '@/hooks/use-mission-plan'
import { fmtCost, fmtUsd } from '@/lib/format'
import { planProgress } from '@/lib/plan-progress'
import type { Tone } from '@/lib/status-tone'
import type { GateMode } from '@/types/mission'
import type { JoinedTask } from './plan-board-types'
import { PRE_RUN_GATE_KEY } from './plan-board-types'

const GATE_OPTIONS: { value: GateMode; label: string; title: string }[] = [
  { value: 'interactive', label: 'Interactive', title: 'Human in the loop: you approve every task' },
  { value: 'manual', label: 'Manual', title: 'External approval' },
  { value: 'ai_assisted', label: 'AI-assisted', title: 'AI approves, you can veto' },
  { value: 'autonomous', label: 'Autonomous', title: 'Unattended: the supervisor drives the loop' },
]

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
  const { data: lastDecision } = useLastSupervisorDecision(missionId, plan.status)
  const [gateOpen, setGateOpen] = useState(false)

  const approvedTasks = joined.filter(
    (j) => j.effectiveStatus === 'approved' || j.effectiveStatus === 'queued',
  )
  const approvedCount = approvedTasks.length

  const hasBudget = plan.budget_usd_ceiling != null && plan.budget_usd_ceiling > 0
  const budgetPct = hasBudget ? (plan.total_spent_usd / plan.budget_usd_ceiling!) * 100 : 0
  const budgetTone: Tone = budgetPct > 80 ? 'danger' : budgetPct > 50 ? 'warning' : 'brand'

  const { done, total } = planProgress(plan)
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
      if (result.outcome_status === 'dispatching') {
        toast.success('Dispatched — streaming progress via console')
      } else {
        toast.success(`Run ${result.outcome_status} — ${fmtCost(result.total_cost_usd)}`)
      }
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
      <Panel className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 px-3.5 py-2.5">
        <span className="text-base font-medium">Plan</span>
        <Badge variant="outline" className="font-mono">v{plan.version}</Badge>

        <Segmented
          label="Autonomy mode"
          value={plan.gate_mode}
          onChange={handleGateMode}
          options={GATE_OPTIONS}
          disabled={updatePlan.isPending}
        />

        {total > 0 && (
          <div className="flex items-center gap-2">
            <Progress label="Plan progress" value={(done / total) * 100} tone="success" className="w-16" />
            <span className="font-mono text-xs text-muted-foreground">{done} of {total}</span>
          </div>
        )}

        {hasBudget && (
          <div className="flex items-center gap-2" title="Spent of the plan budget">
            <span className="font-mono text-xs text-muted-foreground">
              {fmtUsd(plan.total_spent_usd)} / {fmtUsd(plan.budget_usd_ceiling!)}
            </span>
            <Progress label="Budget used" value={budgetPct} tone={budgetTone} className="w-14" />
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="secondary"
            aria-pressed={refineOpen}
            onClick={onToggleRefine}
            title="Refine the plan with the Planning Agent"
          >
            <Sparkles className="h-[13px] w-[13px]" />
            Refine plan
          </Button>
          <Button
            variant={isPlanPaused ? 'default' : 'destructive'}
            onClick={handlePlanPauseToggle}
            disabled={updatePlan.isPending}
            title={isPlanPaused ? 'Resume autonomous dispatch' : 'Stop autonomous dispatch'}
          >
            {isPlanPaused ? <Play className="h-[13px] w-[13px]" /> : <Square className="h-[13px] w-[13px]" />}
            {isPlanPaused ? 'Resume plan' : 'Stop plan'}
          </Button>
          <Button
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
              <Loader2 className="h-[13px] w-[13px] animate-spin motion-reduce:animate-none" />
            ) : (
              <Play className="h-[13px] w-[13px]" />
            )}
            Run approved{approvedCount > 0 ? ` (${approvedCount})` : ''}
          </Button>
        </div>
      </Panel>

      {isPlanPaused && lastDecision?.action === 'escalate' && (
        <div className="flex shrink-0 items-start gap-2.5 rounded-panel border border-danger/20 bg-danger/5 px-4 py-3">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
          <div className="min-w-0">
            <span className="text-sm font-medium text-danger">Supervisor escalated</span>
            <p className="mt-0.5 text-xs text-danger/80 [overflow-wrap:anywhere]">{lastDecision.reason}</p>
          </div>
        </div>
      )}

      {gateOpen && (
        <PreRunGateModal
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
  approvedTasks,
  isPending,
  onConfirm,
  onCancel,
}: {
  approvedTasks: JoinedTask[]
  isPending: boolean
  onConfirm: (skipNextTime: boolean) => void
  onCancel: () => void
}) {
  const [skipNextTime, setSkipNextTime] = useState(false)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/60 backdrop-blur-sm" onClick={onCancel}>
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label="Ready to run?"
        className="w-full max-w-sm p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-medium">Ready to run?</h3>
          <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={onCancel}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <p className="mb-3 text-xs text-muted-foreground">
          {approvedTasks.length} task{approvedTasks.length !== 1 ? 's' : ''} will be dispatched:
        </p>

        <div className="mb-4 max-h-48 space-y-1 overflow-y-auto">
          {approvedTasks.map((t) => (
            <div key={t.task.id} className="rounded-card bg-raised px-2.5 py-1.5 text-xs">
              <span className="font-medium">{t.task.description || t.task.id}</span>
              <span className="ml-2 text-subtle">{t.task.agent}</span>
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
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(skipNextTime)} disabled={isPending}>
            {isPending ? (
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            Run {approvedTasks.length}
          </Button>
        </div>
      </Panel>
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
      toast.success('Refining plan — updates will appear shortly')
      setInstructions('')
      onDone()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refinement failed')
    }
  }

  return (
    <Panel className="shrink-0 space-y-2 p-3.5">
      <p className="text-xs text-muted-foreground">
        Describe the plan you want. The Planning Agent will produce a new TaskPlan based on the mission
        brief + your instructions. task_ids are preserved for unchanged tasks so approvals and run history
        survive.
      </p>
      <Textarea
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder="e.g. Split the code-quality audit into two tasks: one for style, one for security. Add a final task that summarises findings."
        rows={3}
        className="resize-none text-xs"
        disabled={refine.isPending}
      />
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onDone} disabled={refine.isPending}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={refine.isPending || !instructions.trim()}>
          {refine.isPending ? (
            <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
          ) : (
            <Sparkles className="h-3 w-3" />
          )}
          {refine.isPending ? 'Refining…' : 'Refine plan'}
        </Button>
      </div>
    </Panel>
  )
}
