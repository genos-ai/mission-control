"""
Temporal Activities.

Non-deterministic operations that run outside the Workflow's
deterministic replay. Each Activity is idempotent and safe to retry.
Activities receive IDs and brief strings, not large objects.
"""

import asyncio

from temporalio import activity

from modules.backend.core.logging import get_logger
from modules.backend.temporal.models import (
    MissionExecutionResult,
    MissionWorkflowInput,
    NotificationPayload,
)

logger = get_logger(__name__)



@activity.defn
async def execute_mission(input: MissionWorkflowInput) -> MissionExecutionResult:
    """Execute approved plan tasks via dispatch_approved().

    Uses MissionPlanService.dispatch_approved() which:
    1. Collects approved task_ids from plan_task_states
    2. Derives the subset TaskPlan
    3. Marks tasks as queued
    4. Calls handle_mission(precomputed_plan=...)
    5. Writes back task states (completed/failed) after execution
    6. Updates plan cost totals

    This ensures plan_task_states stay in sync with execution results.
    """
    from redis.asyncio import Redis as AsyncRedis

    from modules.backend.core.config import get_redis_url
    from modules.backend.core.database import get_async_session
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.mission import MissionService
    from modules.backend.services.mission_plan import MissionPlanService

    activity.logger.info(
        "execute_mission started",
        extra={
            "mission_run_id": input.mission_run_id,
            "mission_id": input.mission_id,
            "budget": input.mission_budget_usd,
        },
    )

    redis = AsyncRedis.from_url(get_redis_url())
    event_bus = SessionEventBus(redis, mission_id=input.mission_id)

    async with get_async_session() as db:
        try:
            # Look up mission owner for audit trail
            mission = await MissionService(db).get_mission(input.mission_id)

            svc = MissionPlanService(db, event_bus=event_bus)
            activity.logger.info(
                "execute_mission dispatching",
                extra={"plan_id": input.mission_run_id, "owner": str(mission.owner_id)},
            )
            result = await svc.dispatch_approved(
                input.mission_run_id,
                user_id=mission.owner_id,
                session_id=input.session_id,
                skip_post_run_supervisor=True,
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
                outcome_json=result,
            )

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            # CancelledError is a BaseException — not caught by
            # "except Exception".  When Temporal cancels the activity
            # (timeout or workflow cancellation), this prevents the
            # error from propagating uncaught and causing silent retries.
            activity.logger.warning(
                "Mission execution cancelled",
                extra={"mission_run_id": input.mission_run_id, "mission_id": input.mission_id},
            )
            return MissionExecutionResult(
                mission_id=input.mission_run_id,
                status="failed",
                outcome_json={"error": f"Activity cancelled: {type(e).__name__}"},
            )

        except Exception as e:
            activity.logger.error(
                "Mission execution failed",
                extra={"mission_run_id": input.mission_run_id, "error": str(e), "mission_id": input.mission_id},
                exc_info=True,
            )
            # Emit error event so it surfaces in the Console
            try:
                import uuid
                from modules.backend.events.types import SystemEvent
                await event_bus.publish_to_mission(
                    input.mission_id,
                    SystemEvent(
                        session_id=uuid.uuid4(),
                        source="mission_execution",
                        level="error",
                        message=f"Mission execution failed: {str(e)[:250]}",
                        mission_id=input.mission_id,
                    ),
                )
            except Exception:
                pass  # best-effort
            return MissionExecutionResult(
                mission_id=input.mission_run_id,
                status="failed",
                outcome_json={"error": str(e)},
            )
        finally:
            await redis.aclose()


@activity.defn
async def persist_mission_outcome(
    mission_run_id: str,
    session_id: str,
    roster_name: str,
    outcome_json: dict,
    mission_id: str | None = None,
) -> bool:
    """Persist mission results to PostgreSQL. Best-effort."""
    from modules.backend.agents.mission_control.outcome import ExecutionOutcome
    from modules.backend.agents.mission_control.persistence_bridge import (
        persist_mission_results,
    )
    from modules.backend.core.database import get_async_session

    try:
        outcome = ExecutionOutcome.model_validate(outcome_json)
        async with get_async_session() as db:
            await persist_mission_results(
                outcome,
                session_id=session_id,
                roster_name=roster_name,
                task_plan_json=outcome_json.get("task_plan_reference"),
                thinking_trace=outcome_json.get("planning_trace_reference"),
                mission_id=mission_id,
                db_session=db,
            )
            await db.commit()
        return True
    except (OSError, ValueError, RuntimeError) as e:
        activity.logger.error(
            "Failed to persist mission results",
            extra={"mission_run_id": mission_run_id, "error": str(e), "mission_id": mission_id},
        )
        # Emit error event so it surfaces in the Console
        if mission_id:
            try:
                import uuid
                from modules.backend.core.config import get_redis_url
                from modules.backend.events.bus import SessionEventBus
                from modules.backend.events.types import SystemEvent
                from redis.asyncio import Redis as AsyncRedis

                redis = AsyncRedis.from_url(get_redis_url())
                try:
                    bus = SessionEventBus(redis, mission_id=mission_id)
                    await bus.publish_to_mission(
                        mission_id,
                        SystemEvent(
                            session_id=uuid.uuid4(),
                            source="mission_persistence",
                            level="error",
                            message=f"Failed to persist mission results: {str(e)[:200]}",
                            mission_id=mission_id,
                        ),
                    )
                finally:
                    await redis.aclose()
            except Exception:
                pass  # best-effort
        return False


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
