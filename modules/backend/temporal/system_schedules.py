"""System schedule registration (Plan 88 step 88.0.10, contract 3.3.2).

The worker registers every key of `temporal.system_schedules` at startup with
create-or-update. Each key needs a builder in _BUILDERS; a key without one
raises, so config and code cannot drift apart silently.
"""

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleUpdate,
)

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.temporal.config_snapshots import config_hash, policy_snapshot
from modules.backend.temporal.mission_run_models import ReconcilerInput
from modules.backend.temporal.reconciler_workflow import ReconcilerWorkflow

if TYPE_CHECKING:
    from modules.backend.core.config_schema import TemporalSchema

logger = get_logger(__name__)


def _reconciler_action(temporal: "TemporalSchema") -> tuple[Callable[..., Any], ReconcilerInput]:
    inp = ReconcilerInput(
        config_hash="",
        orphan_grace_seconds=temporal.reconciler.orphan_grace_seconds,
        activity=policy_snapshot(temporal.reconciler.activity),
    )
    return ReconcilerWorkflow.run, dataclasses.replace(inp, config_hash=config_hash(inp))


_BUILDERS: dict[str, Callable[["TemporalSchema"], tuple[Callable[..., Any], Any]]] = {
    "reconciler": _reconciler_action,
}


async def register_system_schedules(client: Client) -> None:
    """Create or update one Temporal schedule per `temporal.system_schedules` key."""
    temporal = get_app_config().temporal
    unknown = sorted(set(temporal.system_schedules) - set(_BUILDERS))
    if unknown:
        raise RuntimeError(f"No schedule builder for system_schedules keys: {', '.join(unknown)}")

    for key, entry in temporal.system_schedules.items():
        schedule_id = f"system-{key}"
        fn, arg = _BUILDERS[key](temporal)
        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                fn, arg, id=schedule_id, task_queue=temporal.task_queue
            ),
            spec=ScheduleSpec(cron_expressions=[entry.cron]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )
        try:
            await client.create_schedule(schedule_id, schedule)
            logger.info("System schedule created", extra={"schedule_id": schedule_id})
        except ScheduleAlreadyRunningError:
            await client.get_schedule_handle(schedule_id).update(
                lambda _: ScheduleUpdate(schedule=schedule)
            )
            logger.info("System schedule updated", extra={"schedule_id": schedule_id})
