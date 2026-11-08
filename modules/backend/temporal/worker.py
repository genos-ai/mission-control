"""
Temporal Worker.

Starts a Temporal Worker that executes AgentMissionWorkflow and its
Activities. Run via CLI: python -m modules.backend.temporal.worker
"""

import asyncio

from temporalio.worker import Worker

from modules.backend.core.logging import get_logger
from modules.backend.temporal.activities import (
    execute_mission,
    persist_mission_outcome,
    send_notification,
)
from modules.backend.temporal.chat_activities import execute_chat_turn, persist_user_message
from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
from modules.backend.temporal.client import get_temporal_client, get_temporal_config
from modules.backend.temporal.human_input_activities import (
    mark_human_input_resolved,
    notify_human_input_needed,
)
from modules.backend.temporal.human_input_workflow import HumanInputWorkflow
from modules.backend.temporal.knowledge_activities import (
    backfill_embeddings,
    embed_source,
    extract_all_missions,
    extract_mission_learnings,
    run_knowledge_officer,
)
from modules.backend.temporal.knowledge_workflow import (
    EmbeddingBackfillWorkflow,
    KnowledgeExtractionWorkflow,
    KnowledgeOfficerWorkflow,
)
from modules.backend.temporal.maintenance_activities import (
    run_cleanup_stale_environments,
    run_daily_cleanup,
    run_evaluate_workflow_schedules,
    run_hourly_health_check,
    run_metrics_aggregation,
    run_weekly_report_generation,
)
from modules.backend.temporal.maintenance_workflow import (
    CleanupEnvironmentsWorkflow,
    DailyCleanupWorkflow,
    EvaluateWorkflowSchedulesWorkflow,
    HourlyHealthCheckWorkflow,
    MetricsAggregationWorkflow,
    WeeklyReportWorkflow,
)
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from modules.backend.temporal.plan_refine_activities import execute_plan_refine
from modules.backend.temporal.plan_refine_workflow import PlanRefineWorkflow
from modules.backend.temporal.reconciler_activities import reconcile_mission_runs
from modules.backend.temporal.reconciler_workflow import ReconcilerWorkflow
from modules.backend.temporal.run_objective_activities import execute_run_objective
from modules.backend.temporal.run_objective_workflow import RunObjectiveWorkflow
from modules.backend.temporal.scheduled_activities import find_ready_plans
from modules.backend.temporal.scheduled_workflow import ScheduledMissionCheckWorkflow
from modules.backend.temporal.supervisor_activities import (
    approve_proposed_tasks,
    check_plan_active,
    evaluate_post_run,
    fetch_plan_task_counts,
    fire_supervisor_followups,
    start_director_turn,
)
from modules.backend.temporal.system_schedules import register_system_schedules
from modules.backend.temporal.tool_fork_activities import (
    execute_design_workflow,
    execute_run_workflow,
    notify_director_on_completion,
    update_execution_record_status,
)
from modules.backend.temporal.tool_fork_workflow import DesignWorkflowWorkflow, RunWorkflowWorkflow
from modules.backend.temporal.workflow import AgentMissionWorkflow

logger = get_logger(__name__)


async def start_worker() -> None:
    """Start the Temporal Worker."""
    config = get_temporal_config()
    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue=config.task_queue,
        workflows=[
            AgentMissionWorkflow,
            ChatTurnWorkflow,
            MissionRunWorkflow,
            ScheduledMissionCheckWorkflow,
            DesignWorkflowWorkflow,
            RunWorkflowWorkflow,
            # Human input (Plan 45 Phase 4)
            HumanInputWorkflow,
            # Knowledge platform (Plan 57)
            KnowledgeExtractionWorkflow,
            KnowledgeOfficerWorkflow,
            EmbeddingBackfillWorkflow,
            # Plan endpoints (async-only)
            PlanRefineWorkflow,
            RunObjectiveWorkflow,
            # Maintenance (Plan 56 Phase C — replaces TaskIQ cron)
            DailyCleanupWorkflow,
            HourlyHealthCheckWorkflow,
            WeeklyReportWorkflow,
            MetricsAggregationWorkflow,
            CleanupEnvironmentsWorkflow,
            EvaluateWorkflowSchedulesWorkflow,
            # Run reconciliation (Plan 88 step 88.0.10)
            ReconcilerWorkflow,
        ],
        activities=[
            # Mission execution (Plan 16)
            execute_mission,
            persist_mission_outcome,
            send_notification,
            # Chat turn (Plan 52 Phase B)
            persist_user_message,
            execute_chat_turn,
            # Supervisor loop (Plan 52 Phase C)
            evaluate_post_run,
            approve_proposed_tasks,
            fetch_plan_task_counts,
            start_director_turn,
            check_plan_active,
            fire_supervisor_followups,
            # Scheduled dispatch (Plan 52 Phase D)
            find_ready_plans,
            # Plan endpoints (async-only)
            execute_plan_refine,
            execute_run_objective,
            # Tool fork (Plan 56 Phase B)
            execute_design_workflow,
            execute_run_workflow,
            notify_director_on_completion,
            update_execution_record_status,
            # Human input (Plan 45 Phase 4)
            notify_human_input_needed,
            mark_human_input_resolved,
            # Knowledge platform (Plan 57)
            extract_mission_learnings,
            extract_all_missions,
            embed_source,
            backfill_embeddings,
            run_knowledge_officer,
            # Maintenance (Plan 56 Phase C — replaces TaskIQ cron)
            run_daily_cleanup,
            run_hourly_health_check,
            run_weekly_report_generation,
            run_metrics_aggregation,
            run_cleanup_stale_environments,
            run_evaluate_workflow_schedules,
            # Run reconciliation (Plan 88 step 88.0.10)
            reconcile_mission_runs,
        ],
    )

    from modules.backend.core.logging import start_mission_event_drain

    start_mission_event_drain()

    logger.info(
        "Temporal worker starting",
        extra={"task_queue": config.task_queue},
    )

    # Fail closed: a registration failure stops the worker from starting.
    await register_system_schedules(client)

    await worker.run()


def main() -> None:
    """Entry point for running the worker."""
    # Initialise the same logging pipeline as the backend so worker
    # errors, activity logs, and workflow events all appear in
    # var/logs/system.jsonl alongside the API server's logs.
    from modules.backend.core.logging import setup_logging
    from modules.backend.core.tls import configure_tls_trust

    setup_logging(enable_mission_events=True)
    configure_tls_trust()

    asyncio.run(start_worker())


if __name__ == "__main__":
    main()
