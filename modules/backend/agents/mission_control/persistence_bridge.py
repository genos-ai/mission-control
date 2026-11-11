"""Bridge between Mission Control dispatch and the persistence layer.

Converts ExecutionOutcome (in-memory) to persisted ExecutionRecord (database).
Raises on failure; only per-artifact creation is best-effort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.backend.agents.mission_control.outcome import (
    ExecutionOutcome,
    ExecutionStatus,
)
from modules.backend.core.logging import get_logger
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_artifact import MissionArtifactService
from modules.backend.services.task_result_persistence import persist_task_result

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def persist_mission_results(
    outcome: ExecutionOutcome,
    *,
    session_id: str,
    roster_name: str | None = None,
    thinking_trace: str | None = None,
    mission_id: str | None = None,
    db_session: AsyncSession,
    execution_record_id: str | None = None,
) -> str:
    """Persist execution results. Raises on failure; the caller's activity retry policy decides.

    Returns the ExecutionRecord id.

    When ``execution_record_id`` is provided, the existing record
    (created at dispatch start) is updated with final results instead
    of inserting a new row.  This two-phase pattern ensures the run
    is visible in the UI while it executes.
    """
    try:
        service = ExecutionPersistenceService(db_session)
        # Plan 43: extract durable artifacts alongside the execution
        # persistence so overnight autonomous runs produce output that
        # survives page refresh and backend restart. Only instantiated
        # when mission_id is set — artifacts are mission-scoped by
        # definition (the mission_id FK is NOT NULL).
        artifact_svc = MissionArtifactService(db_session) if mission_id else None

        status_map = {
            ExecutionStatus.SUCCESS: "completed",
            ExecutionStatus.PARTIAL: "completed",
            ExecutionStatus.FAILED: "failed",
        }
        record_status = status_map.get(outcome.status, "failed")

        if execution_record_id:
            record = await service.complete_execution(
                execution_record_id=execution_record_id,
                status=record_status,
                roster_name=roster_name,
                execution_outcome_json=outcome.model_dump(),
                planning_thinking_trace=thinking_trace,
                total_cost_usd=outcome.total_cost_usd,
            )
        else:
            record = await service.save_execution(
                session_id=session_id,
                status=record_status,
                roster_name=roster_name,
                execution_outcome_json=outcome.model_dump(),
                planning_thinking_trace=thinking_trace,
                total_cost_usd=outcome.total_cost_usd,
                mission_id=mission_id,
            )

        # Batch-fetch domain_tags for all tasks in one query (Plan 72)
        from modules.backend.services.mission_plan import MissionPlanService

        task_ids = [tr.task_id for tr in outcome.task_results if tr.task_id]
        domain_tags_map = await MissionPlanService(db_session).get_domain_tags_map(task_ids)

        for task_result in outcome.task_results:
            await persist_task_result(
                service,
                execution_record_id=record.id,
                task_result=task_result,
                mission_id=mission_id,
                domain_tags=domain_tags_map.get(task_result.task_id),
                mission_run_id=None,
                idempotency_key=None,
                artifact_svc=artifact_svc,
            )

        await db_session.commit()

        logger.info(
            "Execution results persisted",
            extra={
                "execution_record_id": record.id,
                "task_count": len(outcome.task_results),
            },
        )
        return record.id

    except (OSError, ValueError, RuntimeError) as e:
        # non-critical log: the error is re-raised below; no event_bus is
        # threaded through this bridge, so the calling activity emits the event.
        logger.error(
            "Failed to persist execution results",
            extra={"session_id": session_id, "error": str(e), "mission_id": mission_id},
        )
        await db_session.rollback()
        raise
