/**
 * useMissionPlan and related hooks (Plan 42 → Plan 72).
 *
 * Read + mutate the long-lived mission backlog via the REST endpoints
 * in modules/backend/api/v1/endpoints/missions_plan.py.
 *
 * Plan 72 promoted Task to a first-class DB entity — tasks are now
 * unified objects (definition + state merged) returned as a flat array
 * on the plan response.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { GateMode } from '@/types/mission'

// ── Types ────────────────────────────────────────────────────────────────

export type PlanTaskStatus =
  | 'proposed'
  | 'approved'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'cancelled'

export type MissionPlanStatus = 'active' | 'paused' | 'completed' | 'archived'

/** Unified task: definition fields + state fields merged (Plan 72). */
export interface PlanTask {
  id: string
  plan_id: string
  mission_id: string
  agent: string
  description: string
  instructions: string
  inputs_json: Record<string, unknown>
  verification_json: Record<string, unknown>
  constraints_json: Record<string, unknown>
  domain_tags: string[]
  dependencies: string[]
  status: PlanTaskStatus
  approved_by_user_id: string | null
  approved_at: string | null
  retry_count: number
  last_attempt_at: string | null
  result_summary: string | null
  failure_reason: string | null
  cost_usd: number
  duration_seconds: number
  created_at: string
  updated_at: string
}

export interface MissionPlan {
  id: string
  mission_id: string
  summary: string | null
  estimated_cost_usd: number | null
  estimated_duration: number | null
  execution_hints_json: Record<string, unknown> | null
  gate_mode: GateMode
  status: MissionPlanStatus
  version: number
  budget_usd_ceiling: number | null
  total_spent_usd: number
  tasks: PlanTask[]
  created_at: string
  updated_at: string
}

export interface TaskTransitionResult {
  target_task_id: string
  transitioned_task_ids: string[]
  new_status: PlanTaskStatus
}

export interface DispatchApprovedResult {
  outcome_status: 'dispatching'
  dispatched_task_ids: string[]
  total_cost_usd: number
  new_total_spent_usd: number
  workflow_id: string | null
}

// ── Query keys ───────────────────────────────────────────────────────────

export const planKeys = {
  plan: (missionId: string) => ['missions', missionId, 'plan'] as const,
}

// ── Queries ──────────────────────────────────────────────────────────────

/**
 * Fetch the mission's plan + all tasks.
 *
 * The plan is created lazily on the backend, so every valid mission has a
 * plan — if no refinement has happened yet, `tasks` is empty. Use that
 * as the "empty state" signal.
 */
export function useMissionPlan(missionId: string | undefined) {
  return useQuery({
    queryKey: planKeys.plan(missionId!),
    queryFn: () =>
      api.get<MissionPlan>(`/missions/${missionId}/plan`),
    enabled: !!missionId,
  })
}

// ── Mutations ────────────────────────────────────────────────────────────

/** Refine the plan via the Planning Agent (async — returns immediately).
 *
 * Starts a PlanRefineWorkflow via Temporal. The plan cache is invalidated
 * when the mission_plan.refined SSE event arrives (handled in layout.tsx).
 */
export function useRefinePlan(missionId: string) {
  return useMutation({
    mutationFn: (instructions: string) =>
      api.post<{ status: string; plan_id: string; workflow_id?: string }>(
        `/missions/${missionId}/plan/refine`,
        { instructions },
      ),
  })
}

/** Update plan-level settings (gate_mode / status / budget). */
export interface PlanUpdatePayload {
  gate_mode?: GateMode
  status?: MissionPlanStatus
  budget_usd_ceiling?: number
}

export function useUpdatePlan(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: PlanUpdatePayload) =>
      api.patch<MissionPlan>(`/missions/${missionId}/plan`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Add a single proposed task to the plan manually. */
export function useAddPlanTask(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { description: string; agent: string; instructions?: string; dependencies?: string[] }) =>
      api.post<MissionPlan>(`/missions/${missionId}/plan/tasks`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Approve a task (backend walks transitive dependencies). */
export function useApproveTask(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) =>
      api.post<TaskTransitionResult>(
        `/missions/${missionId}/plan/tasks/${encodeURIComponent(taskId)}/approve`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Reject a task (backend cancels transitive dependents). */
export function useRejectTask(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) =>
      api.post<TaskTransitionResult>(
        `/missions/${missionId}/plan/tasks/${encodeURIComponent(taskId)}/reject`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Retry a failed task (moves failed → approved). */
export function useRetryTask(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) =>
      api.post<TaskTransitionResult>(
        `/missions/${missionId}/plan/tasks/${encodeURIComponent(taskId)}/retry`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Fetch the latest supervisor decision for a paused plan. */
export function useLastSupervisorDecision(
  missionId: string | undefined,
  planStatus: string | undefined,
) {
  return useQuery({
    queryKey: ['missions', missionId, 'supervisor-decision'],
    queryFn: async () => {
      const history = await api.get<{ events: Array<{ event_type: string; data: Record<string, unknown> }> }>(
        `/missions/${missionId}/console/history?limit=50`,
      )
      const decisions = history.events
        ?.filter((e) => e.event_type === 'mission_plan.supervisor_decision')
      const decision = decisions?.[0]
      if (!decision) return null
      const data = decision.data as Record<string, unknown>
      return {
        action: (data.action as string) || '',
        reason: (data.reason as string) || '',
      }
    },
    enabled: !!missionId && planStatus === 'paused',
    staleTime: 60_000,
  })
}

/** Dispatch all currently-approved tasks via Temporal. */
export function useDispatchApproved(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api.post<DispatchApprovedResult>(
        `/missions/${missionId}/plan/dispatch`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}
