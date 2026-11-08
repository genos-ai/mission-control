"""Plan 88 Phase 0 (88.0.2): activity options built from policy snapshots."""

from datetime import timedelta

from modules.backend.core.config import get_app_config
from modules.backend.temporal.activity_options import NON_RETRYABLE, activity_kwargs, retry_policy
from modules.backend.temporal.config_snapshots import policy_snapshot
from modules.backend.temporal.mission_run_models import RetrySnapshot


def test_retry_policy_maps_snapshot() -> None:
    snap = RetrySnapshot(
        initial_interval_seconds=3,
        backoff_coefficient=1.5,
        maximum_interval_seconds=45,
        maximum_attempts=7,
    )
    policy = retry_policy(snap)
    assert policy.initial_interval == timedelta(seconds=3)
    assert policy.backoff_coefficient == 1.5
    assert policy.maximum_interval == timedelta(seconds=45)
    assert policy.maximum_attempts == 7
    assert policy.non_retryable_error_types == NON_RETRYABLE


def test_activity_kwargs_heartbeat_only_when_set() -> None:
    activities = get_app_config().temporal.mission_run.activities

    persistence = activity_kwargs(policy_snapshot(activities.persistence))
    assert "heartbeat_timeout" not in persistence

    execute_task = activity_kwargs(policy_snapshot(activities.execute_task))
    assert execute_task["heartbeat_timeout"] == timedelta(seconds=60)
    assert execute_task["start_to_close_timeout"] == timedelta(seconds=3600)
