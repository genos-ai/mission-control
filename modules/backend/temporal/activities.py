"""
Temporal Activities.

Non-deterministic operations that run outside the Workflow's
deterministic replay. Each Activity is idempotent and safe to retry.
Activities receive IDs and brief strings, not large objects.
"""

import asyncio

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.schemas.execution_outcome import ExecutionOutcome
from modules.backend.temporal.activity_helpers import heartbeat_every
from modules.backend.temporal.mission_run_models import ExecuteWaveInput
from modules.backend.temporal.models import MissionExecutionResult, NotificationPayload

logger = get_logger(__name__)


def _format_activity_error(exc: Exception) -> str:
    """Extract a clean, actionable message from activity errors.

    For LLM provider errors (ModelHTTPError, etc.), includes model name,
    status code, and error detail. For all other exceptions, produces a
    generic but informative message without the misleading "LLM" prefix.
    """
    # pydantic_ai.exceptions.ModelHTTPError
    model_name = getattr(exc, "model_name", None)
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)

    if model_name and status_code:
        detail = ""
        if isinstance(body, dict):
            error_info = body.get("error", {})
            detail = error_info.get("message", "") if isinstance(error_info, dict) else str(body)
        return (
            f"LLM call failed: model={model_name}, status={status_code}"
            f"{f' — {detail[:200]}' if detail else ''}"
        )

    return f"{type(exc).__name__}: {str(exc)[:250]}"


@activity.defn
async def execute_mission(input: ExecuteWaveInput) -> MissionExecutionResult:
    """Execute the run's approved tasks as one wave via dispatch_approved().

    MissionPlanOrchestrator.dispatch_approved() marks the run's approved
    tasks queued, dispatches them through handle_mission(precomputed_plan=...),
    writes back task states and updates plan cost totals. begin_mission_run
    owns the session and the run's ExecutionRecord.
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_app_config, get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.repositories.mission_run import MissionRunRepository
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

    interval = get_app_config().temporal.mission_run.task_heartbeat_interval_seconds
    mission_id = ""

    activity.logger.info(
        "execute_mission started",
        extra={"mission_run_id": input.mission_run_id},
    )

    redis = AsyncRedis.from_url(get_redis_url())
    # Bound once the run is loaded: agent-layer code calls bare publish(),
    # which drops events on an unbound bus. None until then.
    event_bus: SessionEventBus | None = None

    async with get_async_session() as db:
        try:
            run = await MissionRunRepository(db).get_by_id(input.mission_run_id)
            mission_id = run.mission_id
            event_bus = SessionEventBus(redis, mission_id=mission_id)
            # Look up mission owner for audit trail
            mission = await MissionService(db).get_mission(mission_id)

            svc = MissionPlanOrchestrator(db, event_bus=event_bus)
            activity.logger.info(
                "execute_mission dispatching",
                extra={"mission_run_id": input.mission_run_id, "owner": str(mission.owner_id)},
            )
            async with heartbeat_every(interval, "executing"):
                result = await svc.dispatch_approved(
                    input.mission_run_id,
                    mission.owner_id,
                    session_id=input.session_id,
                    execution_record_id=input.execution_record_id,
                )
            await db.commit()

            return MissionExecutionResult(
                mission_id=input.mission_run_id,
                status=result.get("outcome_status", "completed"),
                total_cost_usd=result.get("total_cost_usd", 0.0),
                task_count=len(result.get("dispatched_task_ids", [])),
                success_count=len(result.get("updated_task_ids", [])),
                failed_count=0,
                execution_record_id=result.get("execution_record_id"),
                session_id=input.session_id,
                # Use the full serialized ExecutionOutcome if dispatch_approved
                # provided it; otherwise fall back to the summary dict (older
                # code paths that don't include the full outcome).
                outcome_json=result.get("outcome_json", result),
            )

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            # CancelledError is a BaseException — not caught by
            # "except Exception".  Temporal delivers cancellation (timeout
            # or workflow cancellation) through the heartbeat; record it,
            # then re-raise so Temporal sees the cancellation.
            activity.logger.warning(
                "Mission execution cancelled",
                extra={"mission_run_id": input.mission_run_id, "mission_id": mission_id},
            )
            # Emit error event so it surfaces in the Console. No bus means
            # the run never loaded, so there is no mission to tell.
            if event_bus is not None:
                try:
                    import uuid

                    from modules.backend.events.types import SystemEvent

                    await event_bus.publish_to_mission(
                        mission_id,
                        SystemEvent(
                            session_id=uuid.uuid4(),
                            source="mission_execution",
                            level="error",
                            message=f"Mission execution cancelled: {type(e).__name__}",
                            mission_id=mission_id,
                        ),
                    )
                except Exception:
                    logger.debug(
                        "error event publish failed in Temporal activity (best-effort)",
                        exc_info=True,
                    )
            raise

        except Exception as e:
            # Produce a clean, structured error message — especially for
            # LLM provider failures (credits exhausted, auth errors, etc.)
            clean_msg = _format_activity_error(e)
            activity.logger.error(
                "Mission execution failed",
                extra={
                    "mission_run_id": input.mission_run_id,
                    "error": clean_msg,
                    "error_type": type(e).__name__,
                    "mission_id": mission_id,
                },
                exc_info=True,
            )
            # Emit error event so it surfaces in the Console. No bus means
            # the run never loaded, so there is no mission to tell.
            if event_bus is not None:
                try:
                    import uuid

                    from modules.backend.events.types import SystemEvent

                    await event_bus.publish_to_mission(
                        mission_id,
                        SystemEvent(
                            session_id=uuid.uuid4(),
                            source="mission_execution",
                            level="error",
                            message=clean_msg,
                            mission_id=mission_id,
                        ),
                    )
                except Exception:
                    logger.debug(
                        "error event publish failed in Temporal activity (best-effort)",
                        exc_info=True,
                    )
            raise
        finally:
            await redis.aclose()


@activity.defn
async def persist_mission_outcome(
    mission_run_id: str,
    session_id: str,
    outcome_json: dict,
    mission_id: str,
    execution_record_id: str,
) -> bool:
    """Persist mission results to PostgreSQL. Raises on failure; the retry policy decides.

    The fallback path updates the run's ExecutionRecord (execution_record_id);
    it never inserts a second record. Every call then refreshes the record's
    run task counts, which the post-run stall rule reads.
    """
    from modules.backend.agents.mission_control.persistence_bridge import persist_mission_results
    from modules.backend.core.database import get_async_session
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    try:
        outcome = ExecutionOutcome.model_validate(outcome_json)

        # If execution_record_id is set, handle_mission already persisted
        # inline — this Temporal activity is the backup path. Skip to
        # avoid duplicate execution_records, task_executions, and artifacts.
        if outcome.execution_record_id:
            activity.logger.info(
                "Skipping persist — already persisted inline",
                extra={
                    "execution_record_id": outcome.execution_record_id,
                    "mission_id": mission_id,
                },
            )
        else:
            # Inline persistence didn't happen (execution_record_id is None) —
            # this is the crash recovery path. Persist everything into the
            # run's record.
            task_plan_ref = outcome_json.get("task_plan_reference")
            if isinstance(task_plan_ref, str):
                import json

                try:
                    task_plan_ref = json.loads(task_plan_ref)
                except (json.JSONDecodeError, TypeError):
                    task_plan_ref = None

            async with get_async_session() as db:
                await persist_mission_results(
                    outcome,
                    session_id=session_id,
                    roster_name=None,
                    thinking_trace=outcome_json.get("planning_trace_reference"),
                    mission_id=mission_id,
                    db_session=db,
                    execution_record_id=execution_record_id,
                )
                await db.commit()

        async with get_async_session() as db:
            await ExecutionPersistenceService(db).record_run_task_counts(
                execution_record_id, mission_run_id
            )
            await db.commit()
        return True
    except (asyncio.CancelledError, KeyboardInterrupt):
        # Never swallow cancellation — let Temporal handle retry/timeout.
        raise
    except Exception as e:
        error_msg = f"Failed to persist mission results: {type(e).__name__}: {str(e)[:200]}"
        activity.logger.error(
            error_msg,
            extra={
                "mission_run_id": mission_run_id,
                "error_type": type(e).__name__,
                "mission_id": mission_id,
            },
        )
        # Emit error event so it surfaces in the Console
        if mission_id:
            try:
                import uuid

                from redis.asyncio import Redis as AsyncRedis

                from modules.backend.core.config import get_redis_url
                from modules.backend.events.bus import SessionEventBus
                from modules.backend.events.types import SystemEvent

                redis = AsyncRedis.from_url(get_redis_url())
                try:
                    bus = SessionEventBus(redis, mission_id=mission_id)
                    await bus.publish_to_mission(
                        mission_id,
                        SystemEvent(
                            session_id=uuid.uuid4(),
                            source="mission_persistence",
                            level="error",
                            message=error_msg,
                            mission_id=mission_id,
                        ),
                    )
                finally:
                    await redis.aclose()
            except Exception:
                logger.debug(
                    "notification publish failed in Temporal activity (best-effort)", exc_info=True
                )
        raise


@activity.defn
async def send_notification(payload: NotificationPayload) -> bool:
    """Send notification via configured channel.

    Stub implementation — integrate with real Slack/email/webhook SDKs
    when needed. Logs the notification for now.
    """
    activity.logger.info(
        "Notification sent",
        extra={
            "channel": payload.channel,
            "recipient": payload.recipient,
            "title": payload.title,
            "urgency": payload.urgency,
        },
    )
    return True
