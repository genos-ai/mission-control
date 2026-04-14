"""Bridge between Mission Control dispatch and the persistence layer.

Converts ExecutionOutcome (in-memory) to persisted ExecutionRecord (database).
Best-effort — persistence failure does not crash the execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.backend.agents.mission_control.outcome import (
    ExecutionOutcome,
    ExecutionStatus,
    TaskStatus,
)
from modules.backend.core.logging import get_logger
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_artifact import MissionArtifactService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def persist_mission_results(
    outcome: ExecutionOutcome,
    *,
    session_id: str,
    roster_name: str | None = None,
    task_plan_json: dict | None = None,
    thinking_trace: str | None = None,
    mission_id: str | None = None,
    db_session: AsyncSession,
) -> str | None:
    """Persist execution results. Best-effort — does not raise.

    Returns the inserted ExecutionRecord id on success, or None if persistence
    failed (best-effort semantics preserved). Callers that need to link back
    to the run record (Plan 42: MissionPlanService) read this value; callers
    that don't care simply ignore the return.
    """
    try:
        service = ExecutionPersistenceService(db_session)
        # Plan 43: extract durable artifacts alongside the execution
        # persistence so overnight autonomous runs produce output that
        # survives page refresh and backend restart. Only instantiated
        # when mission_id is set — artifacts are mission-scoped by
        # definition (the mission_id FK is NOT NULL).
        artifact_svc = (
            MissionArtifactService(db_session) if mission_id else None
        )

        status_map = {
            ExecutionStatus.SUCCESS: "completed",
            ExecutionStatus.PARTIAL: "completed",
            ExecutionStatus.FAILED: "failed",
        }
        record_status = status_map.get(outcome.status, "failed")

        record = await service.save_execution(
            session_id=session_id,
            status=record_status,
            roster_name=roster_name,
            task_plan_json=task_plan_json,
            execution_outcome_json=outcome.model_dump(),
            planning_thinking_trace=thinking_trace,
            total_cost_usd=outcome.total_cost_usd,
            mission_id=mission_id,
        )

        for task_result in outcome.task_results:
            verification_dict = None
            if task_result.verification_outcome:
                verification_dict = task_result.verification_outcome.model_dump()

            token_dict = None
            if task_result.token_usage:
                token_dict = {
                    "input_tokens": task_result.token_usage.input,
                    "output_tokens": task_result.token_usage.output,
                }

            task_status_map = {
                TaskStatus.SUCCESS: "completed",
                TaskStatus.FAILED: "failed",
                TaskStatus.TIMEOUT: "failed",
                TaskStatus.SKIPPED: "skipped",
            }
            exec_status = task_status_map.get(task_result.status, "failed")

            # Look up domain_tags from the original TaskPlan
            domain_tags = None
            if task_plan_json and "tasks" in task_plan_json:
                for task_def in task_plan_json["tasks"]:
                    if task_def.get("task_id") == task_result.task_id:
                        domain_tags = task_def.get("domain_tags") or None
                        break

            execution = await service.save_task_execution(
                execution_record_id=record.id,
                task_id=task_result.task_id,
                agent_name=task_result.agent_name,
                status=exec_status,
                output_data=task_result.output_reference or None,
                token_usage=token_dict,
                cost_usd=task_result.cost_usd,
                duration_seconds=task_result.duration_seconds,
                verification_outcome=verification_dict,
                execution_id=task_result.execution_id or None,
                domain_tags=domain_tags,
            )

            # Plan 43: extract artifact from this task's output. Same
            # heuristic as the live SSE emission site
            # (agent_executor.py) — summary field first, fall back to
            # result. Best-effort: an extraction failure is logged and
            # swallowed so it cannot block the ExecutionRecord save.
            if artifact_svc is not None and mission_id is not None:
                try:
                    await artifact_svc.extract_from_task_result(
                        mission_id=mission_id,
                        execution_record_id=record.id,
                        task_execution_id=execution.id,
                        task_result=task_result,
                    )
                except Exception as artifact_exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to extract artifact from task result",
                        extra={
                            "task_id": task_result.task_id,
                            "agent": task_result.agent_name,
                            "error": str(artifact_exc),
                            "mission_id": mission_id,
                        },
                    )

            for retry_entry in task_result.retry_history:
                failure_tier_map = {
                    1: "tier_1_structural",
                    2: "tier_2_quality",
                    3: "tier_3_integration",
                    0: "agent_error",
                }
                ft = failure_tier_map.get(retry_entry.failure_tier)

                await service.save_attempt(
                    task_execution_id=execution.id,
                    attempt_number=retry_entry.attempt,
                    status="failed",
                    failure_tier=ft,
                    failure_reason=retry_entry.failure_reason,
                    feedback_provided=retry_entry.feedback_provided,
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
        logger.error(
            "Failed to persist execution results",
            extra={"session_id": session_id, "error": str(e), "mission_id": mission_id},
        )
        return None
