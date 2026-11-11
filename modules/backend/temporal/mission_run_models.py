"""Plan 88 MissionRunWorkflow dataclasses (contracts 3.3.4 and 3.3.5).

Frozen snapshots passed into workflows so workflow code never reads config,
plus the workflow, signal, update and activity I/O dataclasses. Every string
field that carries an enum holds its lowercase value (contract 3.0.2).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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
    examined_mission_runs: int
    failed_mission_runs: int


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
    max_run_duration_seconds: int
    task_heartbeat_interval_seconds: int
    max_failure_digests: int  # failures.supervisor.max_failure_digests (88.2.6)


@dataclass(frozen=True)
class WorkflowTimeoutsSnapshot:
    """Built only by config_snapshots.build_workflow_timeouts_snapshot.

    Pinned into the chat, plan-refine and tool-fork workflow inputs.
    """

    activity_timeout_seconds: int  # temporal.min_activity_timeout_seconds
    persistence_timeout_seconds: int  # temporal.persistence_timeout_seconds
    persistence_retry_max_attempts: int  # temporal.persistence_retry_max_attempts


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
    run_started_at: datetime  # workflow.now() after begin_mission_run (88.2.6)
    excluded_wait_seconds: int  # human approval waits, excluded from the duration (88.2.6)
    pending_gate: PendingGate | None
    last_supervisor_action: str | None
    approved_seq: int
    pause_requested: bool
    paused: bool
    decision: GateDecisionUpdate | None
    last_can_iteration: int  # iteration at the last continue-as-new (88.2.7)
    zero_completion_waves: int = 0  # consecutive waves with no completed task (stall rule)


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
class SupervisorFollowupInput:
    """fire_supervisor_followups input (88.1.8)."""

    mission_id: str
    mission_run_id: str
    execution_record_id: str
    action: str
    reason: str
    reviewer: str
    wave_status: str
    wave_cost_usd: float
    failure_reason: str | None


@dataclass(frozen=True)
class TaskFailureDigest:
    """One distinct failure of a wave or run; built only by digest_failures."""

    task_id: str  # first task with this fingerprint
    origin: str  # FailureOrigin value
    failure_class: str  # FailureClass value
    fingerprint: str
    summary: str  # the first task's failure_reason
    occurrences: int  # tasks sharing the fingerprint


class FailureItem(Protocol):
    """A failed task: ExecuteTaskResult and TaskRepository.failed_tasks_for_run rows qualify."""

    @property
    def task_id(self) -> str: ...
    @property
    def failure_origin(self) -> str | None: ...
    @property
    def failure_class(self) -> str | None: ...
    @property
    def failure_fingerprint(self) -> str | None: ...
    @property
    def failure_reason(self) -> str | None: ...


# FailureOrigin.UNKNOWN and FailureClass.UNKNOWN values; a literal keeps this module free of
# schema imports for the workflow sandbox, and test_failure_digests pins it to the enums.
_UNKNOWN = "unknown"


def digest_failures(items: Iterable[FailureItem], cap: int) -> tuple[list[TaskFailureDigest], int]:
    """Group failures by fingerprint in input order; keep the first ``cap`` groups.

    The only grouping rule for failure digests (contracts 3.3.4, 3.8.6). Each
    group keeps its first item's task_id and summary and counts its items.
    Returns the kept digests and the number of groups dropped. Pure, so the
    workflow sandbox may call it. Rows without a classification (written
    before 88.2.3b) group by failure_reason, with an empty fingerprint, as unknown.
    """
    order: list[tuple[str, str]] = []
    first: dict[tuple[str, str], FailureItem] = {}
    counts: dict[tuple[str, str], int] = {}
    for item in items:
        if item.failure_fingerprint:
            key = (item.failure_fingerprint, "")
        else:
            key = ("", item.failure_reason or "")
        if key not in first:
            order.append(key)
            first[key] = item
            counts[key] = 0
        counts[key] += 1
    digests = [
        TaskFailureDigest(
            task_id=first[key].task_id,
            origin=first[key].failure_origin or _UNKNOWN,
            failure_class=first[key].failure_class or _UNKNOWN,
            fingerprint=key[0],
            summary=first[key].failure_reason or "",
            occurrences=counts[key],
        )
        for key in order[:cap]
    ]
    return digests, max(len(order) - cap, 0)


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
    # The Director's reason when the run ends SUCCEEDED (objective_met) on its
    # declare_objective_met; finalise records the decision with the run's end.
    director_objective_met: str | None = None


@dataclass
class FinaliseRunResult:
    cost_usd: float
    notification: NotificationRequest | None  # None when the user cancelled (3.6.2)


@dataclass
class DirectorTurnInput:
    mission_id: str
    mission_run_id: str
    session_id: str
    prompt: str
    signal_workflow_id: str | None


@dataclass(frozen=True)
class RefinementOutcome:
    """Payload of the refinement_complete signal: how the Director's refine turn ended.

    The turn ends only after any refinement it started for the run has
    committed or failed (refine_plan waits while a run is active), so the
    run's next graph read sees the refined tasks. ``error`` is set when the
    turn itself failed; ``reply`` is the Director's final message, which
    reports a failed refinement in its own words.

    ``objective_met_reason`` is set only when the Director called
    declare_objective_met in the turn: the run then ends SUCCEEDED
    (OBJECTIVE_MET) instead of failing for want of new tasks. It is a
    structured field from the tool call, never parsed from ``reply``, and
    defaults to None so a signal sent before the field existed still decodes.

    ``refined`` is True when the Director called refine_plan in the turn,
    whatever the refine produced. With a declaration it is a contradiction.
    The run's task graph cannot stand in for it: APPROVED tasks blocked by a
    failed upstream task stay in the run without the turn adding anything.
    """

    error: str | None
    reply: str
    objective_met_reason: str | None = None
    refined: bool = False


@dataclass(frozen=True)
class ExecuteTaskInput:
    mission_run_id: str
    task_id: str
    session_id: str
    execution_record_id: str
    budget_headroom_usd: float | None  # None in Phases 2-3; 88.4.6 sets it under p88-budget-caps
    heartbeat_interval_seconds: int


@dataclass(frozen=True)
class ExecuteTaskResult:
    task_id: str
    status: str  # "completed" | "failed" | "skipped" (lowercase TaskStatus values, 3.0.2)
    verification_failed: bool
    cost_usd: float
    idempotent_replay: bool
    failure_reason: str | None  # TaskFailure.summary (contracts 3.8)
    failure_origin: str | None  # FailureOrigin value; set exactly when status == "failed"
    failure_class: str | None  # FailureClass value
    failure_fingerprint: str | None


@dataclass(frozen=True)
class ResolveTaskInput:
    mission_run_id: str
    task_id: str
    action: str  # "retry" | "skip"
