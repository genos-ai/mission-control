"""MissionRunWorkflow activities (Plan 88 step 88.1.8, contract 3.3.5).

Each activity opens its own DB session, builds a SessionEventBus and calls the
matching MissionRunService method. String status fields arrive as lowercase
enum values (contract 3.0.2) and are parsed with Enum(value).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.activity_helpers import heartbeat_every
from modules.backend.temporal.mission_run_models import (
    BeginRunInput,
    BeginRunResult,
    FinaliseRunInput,
    FinaliseRunResult,
    PlanRunInput,
    PlanRunResult,
    RunStatusUpdate,
    RunTaskGraph,
)

if TYPE_CHECKING:
    from modules.backend.services.mission_run import MissionRunService

logger = get_logger(__name__)


@asynccontextmanager
async def _run_service(bind_to_run_id: str | None = None) -> AsyncIterator["MissionRunService"]:
    """A MissionRunService on a fresh session and event bus, closed on exit.

    With bind_to_run_id the bus is bound to that run's mission, so agent-layer
    code that calls bare publish() (the planner) reaches mission_events.
    Without it the bus is unbound and only publish_to_mission() delivers.
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.repositories.mission_run import MissionRunRepository
    from modules.backend.services.mission_run import MissionRunService

    redis = AsyncRedis.from_url(get_redis_url())
    try:
        async with get_async_session() as db:
            mission_id = None
            if bind_to_run_id is not None:
                run = await MissionRunRepository(db).get_by_id(bind_to_run_id)
                mission_id = run.mission_id
            yield MissionRunService(db, SessionEventBus(redis, mission_id=mission_id))
    finally:
        await redis.aclose()


@activity.defn
async def begin_mission_run(input: BeginRunInput) -> BeginRunResult:
    """PENDING to RUNNING; raises RunStartRejectedError after failing the run itself."""
    async with _run_service() as svc:
        return await svc.begin(input.mission_run_id)


@activity.defn
async def plan_mission_run(input: PlanRunInput) -> PlanRunResult:
    """Plan the run's tasks, heartbeating while the planner works."""
    from modules.backend.core.config import get_app_config

    interval = get_app_config().temporal.mission_run.task_heartbeat_interval_seconds
    async with (
        heartbeat_every(interval, phase="planning"),
        _run_service(bind_to_run_id=input.mission_run_id) as svc,
    ):
        return await svc.plan(input.mission_run_id, input.session_id)


@activity.defn
async def fetch_run_task_graph(mission_run_id: str) -> RunTaskGraph:
    """Layers and counts of the run's tasks."""
    async with _run_service() as svc:
        return await svc.task_graph(mission_run_id)


@activity.defn
async def set_mission_run_status(input: RunStatusUpdate) -> None:
    """Transition the run to input.status."""
    from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason

    reason = MissionRunStatusReason(input.reason) if input.reason is not None else None
    async with _run_service() as svc:
        await svc.transition(
            input.mission_run_id, MissionRunStatus(input.status), reason, input.detail
        )


@activity.defn
async def finalise_mission_run(input: FinaliseRunInput) -> FinaliseRunResult:
    """End the run. The notification is logged here; 88.4.5 sends it."""
    from modules.backend.models.mission_run import MissionRunStatus, MissionRunStatusReason

    reason = MissionRunStatusReason(input.reason) if input.reason is not None else None
    async with _run_service() as svc:
        result = await svc.finalise(
            input.mission_run_id,
            MissionRunStatus(input.status),
            reason,
            input.detail,
            director_objective_met=input.director_objective_met,
        )
    if result.notification is not None:
        logger.info(
            "Run-end notification built (not sent before 88.4.5)",
            extra={
                "kind": result.notification.kind,
                "subject_id": result.notification.subject_id,
            },
        )
    return result
