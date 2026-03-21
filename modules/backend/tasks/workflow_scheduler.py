"""
Workflow Scheduler Task.

Background task that periodically evaluates due workflow schedules
and creates workflow runs for each. Bridges WorkflowScheduleService
(which identifies due schedules) with WorkflowRunService (which
executes the workflow).

Registered as a cron task via register_scheduled_tasks().
"""

from typing import Any

from modules.backend.core.logging import get_logger
from modules.backend.core.utils import utc_now

logger = get_logger(__name__)


async def evaluate_workflow_schedules() -> dict[str, Any]:
    """Evaluate due workflow schedules and create runs.

    1. Calls WorkflowScheduleService.evaluate_due_schedules() to find
       schedules that are past their next_fire_at, not on cooldown,
       within daily caps, and within iteration limits.
    2. For each fired schedule, creates a workflow run via
       WorkflowRunService.run_workflow_from_definition().
    3. Returns statistics for monitoring.

    Individual run failures are logged and notified but don't prevent
    processing of remaining schedules.
    """
    from modules.backend.core.database import get_async_session
    from modules.backend.services.execution import ExecutionService
    from modules.backend.services.workflow_run import WorkflowRunService
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    started_at = utc_now()
    fired_schedules: list[dict] = []
    runs_created = 0
    runs_failed = 0

    try:
        async with get_async_session() as db:
            schedule_service = WorkflowScheduleService(db)
            fired_schedules = await schedule_service.evaluate_due_schedules()
            await db.commit()
    except Exception as e:
        logger.error(
            "Failed to evaluate due schedules",
            extra={"error": str(e)},
        )
        return {
            "status": "error",
            "error": str(e),
            "evaluated_at": started_at.isoformat(),
        }

    if not fired_schedules:
        logger.debug("No due schedules found")
        return {
            "status": "completed",
            "schedules_evaluated": 0,
            "runs_created": 0,
            "evaluated_at": started_at.isoformat(),
        }

    for schedule_info in fired_schedules:
        schedule_id = schedule_info["schedule_id"]
        workflow_definition_id = schedule_info["workflow_definition_id"]
        mission_id = schedule_info["mission_id"]
        budget = schedule_info.get("budget_per_run_usd")

        try:
            async with get_async_session() as db:
                run_service = WorkflowRunService(
                    db,
                    execution_service_factory=ExecutionService.factory,
                )
                run = await run_service.run_workflow_from_definition(
                    workflow_definition_id,
                    mission_id,
                    triggered_by=f"scheduler:{schedule_id}",
                    budget_usd=budget,
                )
                await db.commit()

            runs_created += 1
            logger.info(
                "Scheduled workflow run created",
                extra={
                    "schedule_id": schedule_id,
                    "run_id": run.id,
                    "workflow_definition_id": workflow_definition_id,
                    "status": run.status,
                },
            )

        except Exception as e:
            runs_failed += 1
            logger.error(
                "Failed to create scheduled workflow run",
                extra={
                    "schedule_id": schedule_id,
                    "workflow_definition_id": workflow_definition_id,
                    "error": str(e),
                },
            )

            try:
                await _notify_schedule_failure(schedule_id, str(e))
            except Exception:
                logger.debug("Failed to send schedule failure notification", exc_info=True)

    result = {
        "status": "completed",
        "schedules_evaluated": len(fired_schedules),
        "runs_created": runs_created,
        "runs_failed": runs_failed,
        "evaluated_at": started_at.isoformat(),
        "completed_at": utc_now().isoformat(),
    }

    logger.info("Workflow schedule evaluation completed", extra=result)
    return result


async def _notify_schedule_failure(schedule_id: str, error: str) -> None:
    """Send a notification for a schedule processing failure."""
    from modules.backend.core.config import get_app_config

    config = get_app_config().notifications
    if not config.enabled or not config.notify_on_failure:
        return

    from modules.backend.services.run_notifier import RunNotifierService

    await RunNotifierService.notify_schedule_error(schedule_id, error)
