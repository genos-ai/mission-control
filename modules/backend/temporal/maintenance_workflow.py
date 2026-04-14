"""
Maintenance Workflow (Plan 56 Phase C).

Generic one-activity workflow for scheduled maintenance tasks.
Each task is a single activity call — the workflow wrapper provides
Temporal Schedule integration and execution history.

These replace the 6 TaskIQ cron tasks with Temporal Schedules.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from modules.backend.temporal import maintenance_activities
    from modules.backend.temporal.maintenance_activities import MaintenanceResult


@workflow.defn
class DailyCleanupWorkflow:
    """Daily cleanup — 2:00 AM UTC."""

    @workflow.run
    async def run(self) -> MaintenanceResult:
        return await workflow.execute_local_activity(
            maintenance_activities.run_daily_cleanup,
            schedule_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class HourlyHealthCheckWorkflow:
    """Hourly health check."""

    @workflow.run
    async def run(self) -> MaintenanceResult:
        return await workflow.execute_local_activity(
            maintenance_activities.run_hourly_health_check,
            schedule_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class WeeklyReportWorkflow:
    """Weekly report generation — Sunday 6:00 AM UTC."""

    @workflow.run
    async def run(self) -> MaintenanceResult:
        return await workflow.execute_local_activity(
            maintenance_activities.run_weekly_report_generation,
            schedule_to_close_timeout=timedelta(seconds=300),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn
class MetricsAggregationWorkflow:
    """Metrics aggregation — every 15 minutes."""

    @workflow.run
    async def run(self) -> MaintenanceResult:
        return await workflow.execute_local_activity(
            maintenance_activities.run_metrics_aggregation,
            schedule_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class CleanupEnvironmentsWorkflow:
    """Stale environment cleanup — every hour."""

    @workflow.run
    async def run(self) -> MaintenanceResult:
        return await workflow.execute_local_activity(
            maintenance_activities.run_cleanup_stale_environments,
            schedule_to_close_timeout=timedelta(seconds=120),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class EvaluateWorkflowSchedulesWorkflow:
    """Workflow schedule evaluation — every minute."""

    @workflow.run
    async def run(self) -> MaintenanceResult:
        return await workflow.execute_local_activity(
            maintenance_activities.run_evaluate_workflow_schedules,
            schedule_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
