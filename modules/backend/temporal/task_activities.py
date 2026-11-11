"""Per-task activities of MissionRunWorkflow (Plan 88 step 88.2.4, contract 3.3.5).

``execute_plan_task`` runs one approved task: claim (short transaction),
agent call with no transaction open, record (short transaction). It heartbeats
``{"phase": ...}`` throughout. It raises only for infrastructure errors: a
failed agent task, an unavailable execution environment included, returns
``status="failed"``, so Temporal never retries an agent failure.
"""

import asyncio

from redis.asyncio import Redis as AsyncRedis
from temporalio import activity

from modules.backend.agents.mission_control.dispatch.result_builders import failed_result
from modules.backend.agents.mission_control.dispatch.task_runner import run_single_task
from modules.backend.agents.mission_control.runtime import build_dispatch_runtime
from modules.backend.core.config import get_redis_url
from modules.backend.core.database import get_async_session
from modules.backend.core.exceptions import ExecutionEnvironmentError
from modules.backend.core.failure_classification import get_failure_classifier
from modules.backend.core.logging import get_logger
from modules.backend.events.bus import SessionEventBus
from modules.backend.events.mission_run_types import task_failed_event
from modules.backend.schemas.execution_outcome import TaskResult
from modules.backend.services.mission_plan_taskio import load_dependency_outputs
from modules.backend.services.run_task_execution import RunTaskExecutionService, TaskClaim
from modules.backend.temporal.activity_helpers import heartbeat_every
from modules.backend.temporal.mission_run_models import (
    ExecuteTaskInput,
    ExecuteTaskResult,
    ResolveTaskInput,
)

logger = get_logger(__name__)


async def _run_agent(input: ExecuteTaskInput, claim: TaskClaim) -> TaskResult:
    """Build the task's runtime and run it; an unavailable environment fails the task."""
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        bus = SessionEventBus(redis, mission_id=claim.mission_id)
        async with get_async_session() as db:  # read-only use; no commit
            try:
                runtime = await build_dispatch_runtime(
                    db_session=db,
                    event_bus=bus,
                    mission_id=claim.mission_id,
                    session_id=input.session_id,
                    execution_mode=claim.execution_mode,
                    mission_repo_root=claim.mission_repo_root,
                    container_image=None,
                    extra_volumes=None,
                    mission_run_id=input.mission_run_id,
                    task_id=input.task_id,
                )
            except ExecutionEnvironmentError as exc:  # 88.2.3a: fail the task, not the run
                return failed_result(
                    claim.task_definition, get_failure_classifier().from_exception(exc)
                )
            upstream = await load_dependency_outputs(db, input.task_id)
            project_context = None
            if runtime.context_curator is not None:
                project_context = (
                    await runtime.context_curator.get_mission_context(claim.mission_id) or None
                )
            # budget_usd feeds GateContext only; gate=None ignores it.
            return await run_single_task(
                task=claim.task_definition,
                runtime=runtime,
                upstream_outputs=upstream,
                mission_id=claim.mission_id,
                budget_usd=0.0,
                event_bus=bus,
                session_id=input.session_id,
                gate=None,
                project_context=project_context,
            )
    finally:
        await redis.aclose()


async def _publish_task_failed(
    result: TaskResult, input: ExecuteTaskInput, mission_id: str
) -> None:
    """One TaskFailedEvent per recorded failed attempt, after commit (display only)."""
    redis = AsyncRedis.from_url(get_redis_url())
    try:
        await SessionEventBus(redis, mission_id=mission_id).publish(
            task_failed_event(
                result,
                mission_id=mission_id,
                mission_run_id=input.mission_run_id,
                session_id=input.session_id,
            )
        )
    finally:
        await redis.aclose()


def _workflow_cancelled() -> bool:
    """True when the workflow requested the cancellation.

    Worker shutdown and heartbeat timeouts also cancel the activity; the task
    then stays RUNNING so the next attempt re-executes it under the same
    idempotency key (contracts 3.1.9 rule B).
    """
    details = activity.cancellation_details()
    return details is not None and details.cancel_requested


@activity.defn
async def execute_plan_task(input: ExecuteTaskInput) -> ExecuteTaskResult:
    """Run one task of the run idempotently; a replay never calls the agent."""
    async with heartbeat_every(input.heartbeat_interval_seconds, phase="claim") as hb:
        async with get_async_session() as db:
            claim = await RunTaskExecutionService(db).claim(input.mission_run_id, input.task_id)
        if claim.outcome == "replay":
            return claim.stored
        hb.phase = "agent"
        try:
            result = await _run_agent(input, claim)
        except asyncio.CancelledError:
            if _workflow_cancelled():
                async with get_async_session() as db:
                    await RunTaskExecutionService(db).mark_cancelled(
                        input.mission_run_id, input.task_id
                    )
            raise
        hb.phase = "record"
        async with get_async_session() as db:
            recorded = await RunTaskExecutionService(db).record(
                mission_run_id=input.mission_run_id,
                task_id=input.task_id,
                idempotency_key=claim.idempotency_key,
                execution_record_id=input.execution_record_id,
                task_result_json=result.model_dump(mode="json"),
            )
        if recorded.status == "failed" and not recorded.idempotent_replay:
            await _publish_task_failed(result, input, claim.mission_id)
        return recorded


@activity.defn
async def resolve_failed_task(input: ResolveTaskInput) -> None:
    """Retry or skip a failed task of the run."""
    async with get_async_session() as db:
        await RunTaskExecutionService(db).resolve_failed(
            input.mission_run_id, input.task_id, input.action
        )
