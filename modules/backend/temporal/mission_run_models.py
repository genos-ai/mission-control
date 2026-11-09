"""Plan 88 MissionRunWorkflow dataclasses (contracts 3.3.4 and 3.3.5).

Frozen snapshots passed into workflows so workflow code never reads config,
plus the workflow, signal, update and activity I/O dataclasses. Every string
field that carries an enum holds its lowercase value (contract 3.0.2).
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RetrySnapshot:
    initial_interval_seconds: int
    backoff_coefficient: float
    maximum_interval_seconds: int
    maximum_attempts: int


@dataclass(frozen=True)
class ActivityPolicySnapshot:
    start_to_close_seconds: int
    heartbeat_timeout_seconds: int | None
    retry: RetrySnapshot


@dataclass(frozen=True)
class ReconcilerInput:
    """Schedule action input, built by the worker; config_hash covers the other fields."""

    config_hash: str
    orphan_grace_seconds: int
    activity: ActivityPolicySnapshot


@dataclass(frozen=True)
class ReconcileInput:
    orphan_grace_seconds: int


@dataclass
class ScheduleSyncStats:
    synced: int
    failed: int
    deleted_orphans: int
    completed: int


@dataclass
class ReconcileStats:
    examined_tasks: int
    examined_execution_records: int
    examined_workflow_runs: int
    failed_tasks: int
    failed_execution_records: int
    failed_workflow_runs: int
    left_running: int
    left_in_process: int
    schedule_sync: ScheduleSyncStats | None


@dataclass(frozen=True)
class RunConfigSnapshot:
    """Built only by config_snapshots.build_run_config_snapshot.

    config_hash covers every other field.
    """

    config_hash: str
    task_queue: str
    persistence: ActivityPolicySnapshot
    plan_run: ActivityPolicySnapshot
    execute_task: ActivityPolicySnapshot
    evaluate_gate: ActivityPolicySnapshot
    evaluate_post_run: ActivityPolicySnapshot
    director_turn: ActivityPolicySnapshot
    write_digest: ActivityPolicySnapshot
    notify: ActivityPolicySnapshot
    gate_escalate_after_seconds: int
    gate_pause_after_seconds: int
    gate_points_enabled: dict[str, bool]
    refine_wait_seconds: int
    continue_as_new_after_iterations: int
    max_parallel_tasks: int


@dataclass(frozen=True)
class TickConfigSnapshot:
    """Built only by config_snapshots.build_tick_config_snapshot."""

    config_hash: str
    task_queue: str
    claim: ActivityPolicySnapshot
    notify: ActivityPolicySnapshot


@dataclass
class PendingGate:
    gate_request_id: str
    gate_point: str
    task_id: str | None
    opened_at: datetime
    escalated: bool
    timed_out: bool


@dataclass
class GateDecisionUpdate:
    gate_request_id: str
    action: str
    reason: str | None
    decided_by_user_id: str | None
    channel: str


@dataclass
class MissionRunWorkflowState:
    iteration: int
    session_id: str
    execution_record_id: str
    context_version_start: int
    pending_gate: PendingGate | None
    last_supervisor_action: str | None
    approved_seq: int
    pause_requested: bool
    paused: bool
    decision: GateDecisionUpdate | None


@dataclass
class MissionRunWorkflowInput:
    mission_run_id: str
    mission_id: str
    plan_id: str
    config: RunConfigSnapshot
    state: MissionRunWorkflowState | None = None


@dataclass
class MissionScheduleTickInput:
    mission_schedule_id: str
    config: TickConfigSnapshot


@dataclass
class GateDecisionAck:
    gate_request_id: str
    accepted: bool


@dataclass
class PauseRequest:
    requested_by_user_id: str | None
    reason: str


@dataclass
class ResumeRequest:
    requested_by_user_id: str | None


@dataclass
class TasksApprovedSignal:
    task_ids: list[str]


@dataclass
class NotificationRequest:
    kind: str
    mission_id: str
    mission_run_id: str | None
    gate_request_id: str | None
    subject_id: str
    payload: dict


@dataclass
class MissionRunWorkflowStatus:
    mission_run_id: str
    iteration: int
    phase: str
    pending_gate_id: str | None
    pause_requested: bool
    last_supervisor_action: str | None


# Activity I/O (contract 3.3.5)


@dataclass
class ClaimOccurrenceInput:
    mission_schedule_id: str
    scheduled_for: datetime


@dataclass
class ClaimOccurrenceResult:
    outcome: str
    mission_run_id: str | None
    run_input: MissionRunWorkflowInput | None
    notifications: list[NotificationRequest]


@dataclass
class BeginRunInput:
    mission_run_id: str


@dataclass
class BeginRunResult:
    session_id: str
    execution_record_id: str
    context_version_start: int
    gate_mode: str
    previous_run_id: str | None


@dataclass
class PlanRunInput:
    mission_run_id: str
    session_id: str


@dataclass
class PlanRunResult:
    task_ids: list[str]
    status: str
    detail: str | None


@dataclass
class RunTaskGraph:
    layers: list[list[str]]
    proposed: int
    approved: int
    running: int


@dataclass
class RunStatusUpdate:
    mission_run_id: str
    status: str
    reason: str | None
    detail: str | None


@dataclass
class FinaliseRunInput:
    mission_run_id: str
    status: str
    reason: str | None
    detail: str | None


@dataclass
class FinaliseRunResult:
    cost_usd: float
    notification: NotificationRequest


@dataclass
class DirectorTurnInput:
    mission_id: str
    mission_run_id: str
    session_id: str
    prompt: str
    signal_workflow_id: str | None


@dataclass
class ExecuteWaveInput:
    mission_run_id: str
    session_id: str
    execution_record_id: str
