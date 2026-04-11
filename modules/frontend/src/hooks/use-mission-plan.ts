/**
 * useMissionPlan and related hooks (Plan 42).
 *
 * Read + mutate the long-lived mission backlog via the REST endpoints
 * in modules/backend/api/v1/endpoints/missions_plan.py. The plan body
 * is a TaskPlan JSON (see task_plan.py on the backend) — this file only
 * defines wrapper types; callers parse task_plan_json themselves to
 * read task bodies.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'

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

export type GateMode = 'off' | 'interactive' | 'ai_assisted' | 'autonomous'

export interface PlanTaskState {
  id: string
  task_id: string
  status: PlanTaskStatus
  approved_by_user_id: string | null
  approved_at: string | null
  execution_record_id: string | null
  task_execution_id: string | null
  last_attempt_at: string | null
  retry_count: number
  veto_expires_at: string | null
  result_summary: string | null
  failure_reason: string | null
  // Plan 46 Phase 2 #2: per-task metrics denormalised from
  // task_executions at run completion. Default 0.0 for pre-run
  // states (proposed/approved/queued).
  cost_usd: number
  duration_seconds: number
  created_at: string
  updated_at: string
}

/** A single task body from the TaskPlan JSON. */
export interface PlanTaskBody {
  task_id: string
  agent: string
  agent_version: string
  description: string
  instructions: string
  dependencies: string[]
  domain_tags?: string[]
  inputs?: Record<string, unknown>
  verification?: Record<string, unknown>
  constraints?: Record<string, unknown>
}

/** Top-level shape of task_plan_json. Only the fields the UI needs. */
export interface PlanTaskPlanJson {
  version?: string
  mission_id?: string
  summary?: string
  estimated_cost_usd?: number
  estimated_duration_seconds?: number
  tasks: PlanTaskBody[]
}

export interface MissionPlan {
  id: string
  mission_id: string
  task_plan_json: PlanTaskPlanJson | null
  gate_mode: GateMode | null
  status: MissionPlanStatus
  version: number
  budget_usd_ceiling: number | null
  total_spent_usd: number
  veto_window_sec: number | null
  task_states: PlanTaskState[]
  created_at: string
  updated_at: string
}

export interface TaskTransitionResult {
  target_task_id: string
  transitioned_task_ids: string[]
  new_status: PlanTaskStatus
}

export interface DispatchApprovedResult {
  outcome_status: 'success' | 'partial' | 'failed'
  execution_record_id: string | null
  dispatched_task_ids: string[]
  updated_task_ids: string[]
  total_cost_usd: number
  new_total_spent_usd: number
}

// ── Query keys ───────────────────────────────────────────────────────────

export const planKeys = {
  plan: (missionId: string) => ['missions', missionId, 'plan'] as const,
}

// ── Queries ──────────────────────────────────────────────────────────────

/**
 * Fetch the mission's plan + all task states.
 *
 * The plan is created lazily on the backend, so every valid mission has a
 * plan — if no refinement has happened yet, `task_plan_json` is null and
 * `task_states` is empty. Use that as the "empty state" signal.
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

/** Refine the plan via the Planning Agent. */
export function useRefinePlan(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (instructions: string) =>
      api.post<MissionPlan>(`/missions/${missionId}/plan/refine`, {
        instructions,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Update plan-level settings (gate_mode / status / budget / veto / task_order). */
export interface PlanUpdatePayload {
  gate_mode?: GateMode
  status?: MissionPlanStatus
  budget_usd_ceiling?: number
  veto_window_sec?: number
  task_order?: string[]
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

/** Reorder proposed tasks in the plan (drag-to-reorder, Phase 4). */
export function useReorderTasks(missionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskOrder: string[]) =>
      api.patch<MissionPlan>(`/missions/${missionId}/plan`, { task_order: taskOrder }),
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
      api.post<PlanTaskState>(
        `/missions/${missionId}/plan/tasks/${encodeURIComponent(taskId)}/retry`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: planKeys.plan(missionId) })
    },
  })
}

/** Dispatch all currently-approved tasks as a single run. */
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
