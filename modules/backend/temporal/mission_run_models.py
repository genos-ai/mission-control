"""Plan 88 MissionRunWorkflow dataclasses (contract 3.3.4).

Frozen snapshots passed into workflows so workflow code never reads config.
"""

from dataclasses import dataclass


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
