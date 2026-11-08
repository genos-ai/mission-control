"""Convert config schemas into frozen workflow snapshots (Plan 88).

Not a workflow module. The schema import is under TYPE_CHECKING so workflow
modules can import this through imports_passed_through without loading config.
"""

import dataclasses
import hashlib
import json
from typing import TYPE_CHECKING, Any

from modules.backend.temporal.mission_run_models import ActivityPolicySnapshot, RetrySnapshot

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
