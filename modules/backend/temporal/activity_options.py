"""Activity options built from policy snapshots (Plan 88, contract 3.0.1).

Pure and deterministic: imports only the standard library, temporalio and
mission_run_models. The only place a RetryPolicy is built for Plan 88 code.
"""

from datetime import timedelta
from typing import Any

from temporalio.common import RetryPolicy

from modules.backend.temporal.mission_run_models import ActivityPolicySnapshot, RetrySnapshot

NON_RETRYABLE: list[str] = ["BudgetExceededError", "MissionRunStateError", "RunStartRejectedError"]


def retry_policy(p: RetrySnapshot) -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=p.initial_interval_seconds),
        backoff_coefficient=p.backoff_coefficient,
        maximum_interval=timedelta(seconds=p.maximum_interval_seconds),
        maximum_attempts=p.maximum_attempts,
        non_retryable_error_types=NON_RETRYABLE,
    )


def activity_kwargs(p: ActivityPolicySnapshot) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "start_to_close_timeout": timedelta(seconds=p.start_to_close_seconds),
        "retry_policy": retry_policy(p.retry),
    }
    if p.heartbeat_timeout_seconds is not None:
        kwargs["heartbeat_timeout"] = timedelta(seconds=p.heartbeat_timeout_seconds)
    return kwargs
