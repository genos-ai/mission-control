/**
 * Mission run and mission schedule types (Plan 88, contracts 3.5.3).
 *
 * Mirrors backend/schemas/mission_run.py and backend/schemas/mission_schedule.py.
 * Enum fields carry the lowercase enum values the API returns.
 */

export type MissionRunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_gate'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'budget_stopped'
  | 'skipped'
  | 'missed'

export type MissionRunStatusReason =
  | 'objective_met'
  | 'no_further_work'
  | 'supervisor_escalated'
  | 'task_failures'
  | 'planning_failed'
  | 'gate_rejected'
  | 'invalid_gate_mode'
  | 'cancelled_by_user'
  | 'mission_archived'
  | 'budget_run_cap'
  | 'budget_monthly_cap'
  | 'budget_lifetime_cap'
  | 'start_failed'
  | 'orphaned_workflow_closed'
  | 'orphaned_workflow_not_found'
  | 'user_pause'
  | 'gate_timeout'
  | 'overlap'
  | 'mission_not_active'
  | 'schedule_not_active'
  | 'max_runs_reached'
  | 'budget_cap_reached'
  | 'outside_catchup_window'
  | 'superseded'
  | 'not_fired'
  | 'max_duration_exceeded'

export type MissionRunTrigger = 'schedule' | 'manual' | 'director'

export type MissionRunGateMode = 'interactive' | 'manual' | 'ai_assisted' | 'autonomous'

export type MissionRunTaskStatus =
  | 'proposed'
  | 'approved'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'cancelled'

export interface MissionRunResponse {
  id: string
  mission_id: string
  plan_id: string
  schedule_id: string | null
  sequence: number
  trigger: MissionRunTrigger
  triggered_by_user_id: string | null
  scheduled_for: string | null
  previous_run_id: string | null
  objective: string | null
  workflow_definition_id: string | null
  workflow_parameters: Record<string, unknown>
  status: MissionRunStatus
  status_reason: MissionRunStatusReason | null
  status_detail: string | null
  gate_mode: MissionRunGateMode | null
  temporal_workflow_id: string | null
  session_id: string | null
  context_version_start: number | null
  context_version_end: number | null
  iteration_count: number
  budget_cap_usd: number | null
  cost_usd: number
  task_count: number
  completed_task_count: number
  failed_task_count: number
  config_snapshot: Record<string, unknown>
  cancel_requested_at: string | null
  cancel_requested_by_user_id: string | null
  cancel_reason: MissionRunStatusReason | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  updated_at: string
}

export interface MissionRunListResponse {
  runs: MissionRunResponse[]
  next_before_sequence: number | null
}

export interface MissionRunDigestResponse {
  id: string
  mission_run_id: string
  mission_id: string
  schema_version: number
  generator: 'agent' | 'deterministic'
  summary: string
  outcomes: unknown[]
  decisions: unknown[]
  open_items: unknown[]
  context_changes: unknown[]
  metrics: Record<string, unknown>
  generation_cost_usd: number
  created_at: string
}

export interface MissionRunTaskSummary {
  id: string
  agent: string
  description: string
  status: MissionRunTaskStatus
  failure_reason: string | null
  cost_usd: number
  created_at: string
}

export interface MissionRunDetailResponse {
  run: MissionRunResponse
  /** The run's ExecutionRecord; null until the run has begun. */
  execution_record_id: string | null
  digest: MissionRunDigestResponse | null
  tasks: MissionRunTaskSummary[]
}

export interface MissionRunCreate {
  objective: string
}

// ── Schedules ────────────────────────────────────────────────────────────

export type MissionScheduleKind = 'objective' | 'workflow_definition'

export type MissionScheduleStatus = 'active' | 'paused' | 'completed' | 'archived'

export type MissionScheduleCompletedReason = 'end_date_reached' | 'max_runs_reached'

export type TemporalSyncState = 'pending' | 'synced' | 'failed'

export interface MissionScheduleResponse {
  id: string
  mission_id: string
  name: string
  kind: MissionScheduleKind
  objective_template: string | null
  workflow_definition_id: string | null
  workflow_parameters: Record<string, unknown>
  cron_expression: string
  time_zone_name: string
  starts_at: string | null
  ends_at: string | null
  max_runs: number | null
  catch_up_window_seconds: number
  status: MissionScheduleStatus
  completed_reason: MissionScheduleCompletedReason | null
  executed_run_count: number
  last_claimed_scheduled_for: string | null
  temporal_schedule_id: string
  temporal_sync_state: TemporalSyncState
  temporal_synced_at: string | null
  temporal_sync_error: string | null
  tick_config_hash: string | null
  created_by_user_id: string
  created_at: string
  updated_at: string
  /** Filled on the single-schedule query; empty in the list. */
  next_fire_times: string[]
}

export interface MissionScheduleCreate {
  name: string
  kind: MissionScheduleKind
  objective_template?: string | null
  workflow_definition_id?: string | null
  workflow_parameters?: Record<string, unknown>
  cron_expression: string
  time_zone_name: string
  starts_at?: string | null
  ends_at?: string | null
  max_runs?: number | null
  catch_up_window_seconds?: number | null
}

/** Every field optional; `kind` cannot change. */
export interface MissionScheduleUpdate {
  name?: string | null
  objective_template?: string | null
  workflow_definition_id?: string | null
  workflow_parameters?: Record<string, unknown> | null
  cron_expression?: string | null
  time_zone_name?: string | null
  starts_at?: string | null
  ends_at?: string | null
  max_runs?: number | null
  catch_up_window_seconds?: number | null
}
