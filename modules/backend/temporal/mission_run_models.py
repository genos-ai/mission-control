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
