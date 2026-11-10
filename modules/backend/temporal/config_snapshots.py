"""Convert config schemas into frozen workflow snapshots (Plan 88).

Not a workflow module, so it may read config. The schema import is under
TYPE_CHECKING so workflow modules can import this through
imports_passed_through without loading config. build_run_config_snapshot,
build_tick_config_snapshot and build_workflow_timeouts_snapshot are the only
builders of their snapshots.
"""

import dataclasses
import hashlib
import json
from typing import TYPE_CHECKING, Any

from modules.backend.core.config import get_app_config
from modules.backend.temporal.mission_run_models import (
    ActivityPolicySnapshot,
    RetrySnapshot,
    RunConfigSnapshot,
    TickConfigSnapshot,
    WorkflowTimeoutsSnapshot,
)

if TYPE_CHECKING:
    from modules.backend.core.config_schema import ActivityPolicySchema


def policy_snapshot(schema: "ActivityPolicySchema") -> ActivityPolicySnapshot:
    return ActivityPolicySnapshot(
        start_to_close_seconds=schema.start_to_close_seconds,
        heartbeat_timeout_seconds=schema.heartbeat_timeout_seconds,
        retry=RetrySnapshot(
            initial_interval_seconds=schema.retry.initial_interval_seconds,
            backoff_coefficient=schema.retry.backoff_coefficient,
            maximum_interval_seconds=schema.retry.maximum_interval_seconds,
            maximum_attempts=schema.retry.maximum_attempts,
        ),
    )


def config_hash(obj: Any) -> str:
    """SHA-256 of the canonical JSON of a snapshot dataclass, excluding its config_hash field."""
    data = {k: v for k, v in dataclasses.asdict(obj).items() if k != "config_hash"}
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_run_config_snapshot() -> RunConfigSnapshot:
    """Pin temporal.mission_run (minus claim) and the gate settings for one MissionRunWorkflow."""
    config = get_app_config()
    temporal = config.temporal
    run = temporal.mission_run
    activities = run.activities
    points = config.gate.points
    snap = RunConfigSnapshot(
        config_hash="",
        task_queue=temporal.task_queue,
        persistence=policy_snapshot(activities.persistence),
        plan_run=policy_snapshot(activities.plan_run),
        execute_task=policy_snapshot(activities.execute_task),
        evaluate_gate=policy_snapshot(activities.evaluate_gate),
        evaluate_post_run=policy_snapshot(activities.evaluate_post_run),
        director_turn=policy_snapshot(activities.director_turn),
        write_digest=policy_snapshot(activities.write_digest),
        notify=policy_snapshot(activities.notify),
        # temporal.* until 88.4.8 switches both to gate.durable.*
        gate_escalate_after_seconds=temporal.approval_timeout_seconds,
        gate_pause_after_seconds=temporal.escalation_timeout_seconds,
        gate_points_enabled={
            name: getattr(points, name).enabled for name in type(points).model_fields
        },
        refine_wait_seconds=run.refine_wait_seconds,
        continue_as_new_after_iterations=run.continue_as_new_after_iterations,
        max_parallel_tasks=run.max_parallel_tasks,
        max_run_duration_seconds=run.max_run_duration_seconds,
        task_heartbeat_interval_seconds=run.task_heartbeat_interval_seconds,
    )
    return dataclasses.replace(snap, config_hash=config_hash(snap))


def build_tick_config_snapshot() -> TickConfigSnapshot:
    """Pin the claim and notify policies for one MissionScheduleTickWorkflow."""
    temporal = get_app_config().temporal
    activities = temporal.mission_run.activities
    snap = TickConfigSnapshot(
        config_hash="",
        task_queue=temporal.task_queue,
        claim=policy_snapshot(activities.claim),
        notify=policy_snapshot(activities.notify),
    )
    return dataclasses.replace(snap, config_hash=config_hash(snap))


def build_workflow_timeouts_snapshot() -> WorkflowTimeoutsSnapshot:
    """Pin the activity and persistence timeouts for one chat, plan-refine or tool-fork workflow."""
    temporal = get_app_config().temporal
    return WorkflowTimeoutsSnapshot(
        activity_timeout_seconds=temporal.min_activity_timeout_seconds,
        persistence_timeout_seconds=temporal.persistence_timeout_seconds,
        persistence_retry_max_attempts=temporal.persistence_retry_max_attempts,
    )
