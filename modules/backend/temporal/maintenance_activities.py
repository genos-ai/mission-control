"""
Maintenance activities (Plan 56 Phase C).

Temporal activity wrappers for the 6 cron tasks previously run by TaskIQ.
Each activity calls the existing plain async function — no logic duplication.
"""

from dataclasses import dataclass
from typing import Any

from temporalio import activity

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MaintenanceResult:
    """Generic result from a maintenance activity."""

    task_name: str
    status: str = "completed"
    details: dict | None = None
    error: str | None = None


@activity.defn
async def run_daily_cleanup() -> MaintenanceResult:
    """Run daily cleanup of expired records."""
    try:
        from modules.backend.tasks.scheduled import daily_cleanup

        result = await daily_cleanup(older_than_days=30)
        return MaintenanceResult(task_name="daily_cleanup", details=result)
    except Exception as e:
        activity.logger.error("daily_cleanup failed", extra={"error": str(e)}, exc_info=True)
        return MaintenanceResult(task_name="daily_cleanup", status="failed", error=str(e))


@activity.defn
async def run_hourly_health_check() -> MaintenanceResult:
    """Run hourly health checks on external services."""
    try:
        from modules.backend.tasks.scheduled import hourly_health_check

        result = await hourly_health_check()
        return MaintenanceResult(task_name="hourly_health_check", details=result)
    except Exception as e:
        activity.logger.error("hourly_health_check failed", extra={"error": str(e)}, exc_info=True)
        return MaintenanceResult(task_name="hourly_health_check", status="failed", error=str(e))


@activity.defn
async def run_weekly_report_generation() -> MaintenanceResult:
    """Run weekly report generation."""
    try:
        from modules.backend.tasks.scheduled import weekly_report_generation

        result = await weekly_report_generation()
        return MaintenanceResult(task_name="weekly_report_generation", details=result)
    except Exception as e:
        activity.logger.error(
            "weekly_report_generation failed", extra={"error": str(e)}, exc_info=True
        )
        return MaintenanceResult(
            task_name="weekly_report_generation", status="failed", error=str(e)
        )


@activity.defn
async def run_metrics_aggregation() -> MaintenanceResult:
    """Run metrics aggregation every 15 minutes."""
    try:
        from modules.backend.tasks.scheduled import metrics_aggregation

        result = await metrics_aggregation(interval_minutes=15)
        return MaintenanceResult(task_name="metrics_aggregation", details=result)
    except Exception as e:
        activity.logger.error("metrics_aggregation failed", extra={"error": str(e)}, exc_info=True)
        return MaintenanceResult(task_name="metrics_aggregation", status="failed", error=str(e))


@activity.defn
async def run_cleanup_stale_environments() -> MaintenanceResult:
    """Run stale environment cleanup every hour."""
    try:
        from modules.backend.tasks.scheduled import cleanup_stale_environments

        result = await cleanup_stale_environments(
            idle_timeout_minutes=60,
            max_lifetime_hours=24,
        )
        return MaintenanceResult(task_name="cleanup_stale_environments", details=result)
    except Exception as e:
        activity.logger.error(
            "cleanup_stale_environments failed", extra={"error": str(e)}, exc_info=True
        )
        return MaintenanceResult(
            task_name="cleanup_stale_environments", status="failed", error=str(e)
        )


@activity.defn
async def run_evaluate_workflow_schedules() -> MaintenanceResult:
    """Evaluate due workflow schedules and create runs."""
    try:
        from modules.backend.tasks.workflow_scheduler import evaluate_workflow_schedules

        result = await evaluate_workflow_schedules()
        return MaintenanceResult(task_name="evaluate_workflow_schedules", details=result)
    except Exception as e:
        activity.logger.error(
            "evaluate_workflow_schedules failed", extra={"error": str(e)}, exc_info=True
        )
        return MaintenanceResult(
            task_name="evaluate_workflow_schedules", status="failed", error=str(e)
        )
