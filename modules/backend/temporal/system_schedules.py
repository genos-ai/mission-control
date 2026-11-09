"""System schedule registration (Plan 88 steps 88.0.10 and 88.1.10, contract 3.3.2).

The worker registers every key of `temporal.system_schedules` at startup with
create-or-update through TemporalScheduleGateway. The config keys and _BUILDERS
must match exactly, so config and code cannot drift apart silently. Registration
then deletes the ten legacy schedule ids that the API lifespan used to create,
and nothing else.
"""

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.temporal.config_snapshots import config_hash, policy_snapshot
from modules.backend.temporal.knowledge_workflow import (
    EmbeddingBackfillWorkflow,
    KnowledgeExtractionWorkflow,
    KnowledgeOfficerWorkflow,
)
from modules.backend.temporal.maintenance_workflow import (
    CleanupEnvironmentsWorkflow,
    DailyCleanupWorkflow,
    HourlyHealthCheckWorkflow,
    MetricsAggregationWorkflow,
    WeeklyReportWorkflow,
)
from modules.backend.temporal.mission_run_models import ReconcilerInput
from modules.backend.temporal.reconciler_workflow import ReconcilerWorkflow

if TYPE_CHECKING:
    from modules.backend.core.config_schema import TemporalSchema
    from modules.backend.temporal.schedule_gateway import TemporalScheduleGateway

logger = get_logger(__name__)

LEGACY_SCHEDULE_IDS = frozenset(
    {
        "mission-plan-dispatch-schedule",
        "maintenance-daily-cleanup",
        "maintenance-hourly-health-check",
        "maintenance-weekly-report",
        "maintenance-metrics-aggregation",
        "maintenance-cleanup-environments",
        "maintenance-workflow-schedules",
        "knowledge-daily-extraction",
        "knowledge-officer-daily",
        "knowledge-embedding-backfill",
    }
)


def _reconciler_action(temporal: "TemporalSchema") -> tuple[Callable[..., Any], ReconcilerInput]:
    inp = ReconcilerInput(
        config_hash="",
        orphan_grace_seconds=temporal.reconciler.orphan_grace_seconds,
        activity=policy_snapshot(temporal.reconciler.activity),
    )
    return ReconcilerWorkflow.run, dataclasses.replace(inp, config_hash=config_hash(inp))


def _no_arg(
    fn: Callable[..., Any],
) -> Callable[["TemporalSchema"], tuple[Callable[..., Any], None]]:
    return lambda _temporal: (fn, None)


_BUILDERS: dict[str, Callable[["TemporalSchema"], tuple[Callable[..., Any], Any]]] = {
    "reconciler": _reconciler_action,
    # DailyCleanupWorkflow until 88.5.4 introduces RetentionWorkflow.
    "retention": _no_arg(DailyCleanupWorkflow.run),
    "hourly_health_check": _no_arg(HourlyHealthCheckWorkflow.run),
    "weekly_report": _no_arg(WeeklyReportWorkflow.run),
    "metrics_aggregation": _no_arg(MetricsAggregationWorkflow.run),
    "cleanup_environments": _no_arg(CleanupEnvironmentsWorkflow.run),
    "knowledge_extraction": _no_arg(KnowledgeExtractionWorkflow.run),
    "knowledge_officer": _no_arg(KnowledgeOfficerWorkflow.run),
    "embedding_backfill": _no_arg(EmbeddingBackfillWorkflow.run),
}


async def register_system_schedules(gateway: "TemporalScheduleGateway") -> None:
    """Create or update one schedule per `temporal.system_schedules` key; delete legacy ids."""
    cfg = get_app_config().temporal
    if set(_BUILDERS) != set(cfg.system_schedules):
        raise RuntimeError("system schedule registry mismatch")
    for key, sched in cfg.system_schedules.items():
        fn, arg = _BUILDERS[key](cfg)
        action = ScheduleActionStartWorkflow(
            fn, args=[] if arg is None else [arg], id=f"system-{key}", task_queue=cfg.task_queue
        )
        await gateway.upsert(
            f"system-{key}",
            Schedule(
                action=action,
                spec=ScheduleSpec(cron_expressions=[sched.cron], time_zone_name="UTC"),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
    for sid in await gateway.list_ids(None):
        if sid in LEGACY_SCHEDULE_IDS:
            logger.warning("Deleting legacy schedule", extra={"schedule_id": sid})
            await gateway.delete(sid)
