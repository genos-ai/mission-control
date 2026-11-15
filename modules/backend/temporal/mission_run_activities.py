"""MissionRunWorkflow activities (Plan 88 steps 88.1.8, 88.4.5 and 88.4.6, contract 3.3.5).

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
    PauseForRunInput,
    PlanRunInput,
    PlanRunResult,
    RunBudgetCheck,
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
    """End the run; the workflow sends the returned notification (88.4.5)."""
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
    return result


@activity.defn
async def check_run_budget(mission_run_id: str) -> RunBudgetCheck:
    """The run's spend and headroom under its run, monthly and lifetime caps (88.4.6)."""
    from modules.backend.core.database import get_async_session
    from modules.backend.services.budget import BudgetService

    async with get_async_session() as db:
        check = await BudgetService(db).check_run(mission_run_id)
    return RunBudgetCheck(
        run_spent_usd=check.run_spent_usd,
        month_spent_usd=check.month_spent_usd,
        lifetime_spent_usd=check.lifetime_spent_usd,
        headroom_usd=check.headroom_usd,
        breach=check.breach.value if check.breach is not None else None,
    )


@activity.defn
async def pause_mission_for_run(input: PauseForRunInput) -> None:
    """Pause the run's mission for a system reason; a PAUSED or ARCHIVED mission is left as is."""
    from modules.backend.models.mission import MissionPauseReason
    from modules.backend.services.mission_lifecycle import MissionLifecycleService

    reason = MissionPauseReason(input.reason)
    async with MissionLifecycleService.factory() as svc:
        paused = await svc.pause_for_run(input.mission_run_id, reason)
    logger.info(
        "Mission pause for run",
        extra={"mission_run_id": input.mission_run_id, "reason": reason.value, "paused": paused},
    )
