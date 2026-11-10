"""Bridge between Mission Control dispatch and the persistence layer.

Converts ExecutionOutcome (in-memory) to persisted ExecutionRecord (database).
Raises on failure; only per-artifact creation is best-effort.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.backend.agents.mission_control.outcome import (
    ExecutionOutcome,
    ExecutionStatus,
    TaskResult,
    TaskStatus,
)
from modules.backend.core.logging import get_logger
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_artifact import MissionArtifactService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.backend.models.execution_record import TaskExecution

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


_TASK_STATUS_MAP = {
    TaskStatus.SUCCESS: "completed",
    TaskStatus.FAILED: "failed",
    TaskStatus.TIMEOUT: "failed",
    TaskStatus.SKIPPED: "skipped",
}

_FAILURE_TIER_MAP = {
    1: "tier_1_structural",
    2: "tier_2_quality",
    3: "tier_3_integration",
    0: "agent_error",
}


async def persist_task_result(
    service: ExecutionPersistenceService,
    *,
    execution_record_id: str,
    task_result: TaskResult,
    mission_id: str | None,
    domain_tags: list[str] | None,
    mission_run_id: str | None,
    idempotency_key: str | None,
    artifact_svc: MissionArtifactService | None,
) -> TaskExecution:
    """Write one task's task_executions row, its artifact and its retry attempts.

    Does not commit; the caller owns the transaction. The artifact is written
    only when ``artifact_svc`` and ``mission_id`` are set and the agent declares
    produces_artifact; an artifact failure is logged and never fails the row.
    ``artifact_svc`` is required so every caller decides on artifacts explicitly.
    """
    verification_dict = None
    if task_result.verification_outcome:
        verification_dict = task_result.verification_outcome.model_dump()

    token_dict = None
    if task_result.token_usage:
        token_dict = {
            "input_tokens": task_result.token_usage.input,
            "output_tokens": task_result.token_usage.output,
        }

    execution = await service.save_task_execution(
        execution_record_id=execution_record_id,
        task_id=task_result.task_id,
        agent_name=task_result.agent_name,
        status=_TASK_STATUS_MAP.get(task_result.status, "failed"),
        output_data=task_result.output_reference or None,
        token_usage=token_dict,
        cost_usd=task_result.cost_usd,
        duration_seconds=task_result.duration_seconds,
        verification_outcome=verification_dict,
        execution_id=task_result.execution_id or None,
        domain_tags=domain_tags,
        mission_run_id=mission_run_id,
        idempotency_key=idempotency_key,
    )

    # Create artifact if the agent declares produces_artifact.
    # Driven by catalog config, not output heuristics.
    if artifact_svc is not None and mission_id is not None:
        try:
            await _maybe_create_artifact(
                artifact_svc=artifact_svc,
                mission_id=mission_id,
                execution_record_id=execution_record_id,
                task_execution_id=execution.id,
                task_result=task_result,
            )
        except Exception as artifact_exc:  # noqa: BLE001
            # best-effort — artifact creation never fails the task row; no
            # event_bus is threaded through this bridge to surface the failure.
            logger.warning(
                "Failed to create artifact",
                extra={
                    "task_id": task_result.task_id,
                    "agent": task_result.agent_name,
                    "error": str(artifact_exc),
                    "mission_id": mission_id,
                },
            )

    for retry_entry in task_result.retry_history:
        await service.save_attempt(
            task_execution_id=execution.id,
            attempt_number=retry_entry.attempt,
            status="failed",
            failure_tier=_FAILURE_TIER_MAP.get(retry_entry.failure_tier),
            failure_reason=retry_entry.failure_reason,
            feedback_provided=retry_entry.feedback_provided,
        )

    return execution


async def _maybe_create_artifact(
    *,
    artifact_svc: MissionArtifactService,
    mission_id: str,
    execution_record_id: str,
    task_execution_id: str,
    task_result,
) -> None:
    """Create a mission_artifact if the agent declares produces_artifact.

    Looks up the agent in the registry. If produces_artifact is true,
    extracts content from the task output and writes an artifact row.
    No heuristics — the catalog flag is the single source of truth.
    """

    from modules.backend.agents.mission_control.registry import get_registry

    agent_name = task_result.agent_name or ""
    if not agent_name:
        return

    # Research loop wraps agent names: "research(research.strategist.agent)"
    # Strip the wrapper to find the catalog entry, but check all agents
    # involved in the research loop — the synthesizer produces the artifact.
    registry = get_registry()
    catalog_name = agent_name

    # For research loop tasks, check if the synthesizer (which produces
    # the artifact) was involved. The output contains the synthesizer's
    # report regardless of which agent name the loop is tagged with.
    is_research_loop = agent_name.startswith("research(")
    if is_research_loop:
        # The synthesizer is the artifact producer in research loops
        catalog_name = "research.synthesizer.agent"

    if not registry.has(catalog_name):
        return

    config = registry.get(catalog_name)
    if not config.produces_artifact:
        return

    output = task_result.output_reference or {}
    if not isinstance(output, dict):
        return

    # Extract content — handle both direct output and research loop
    # output where the report is nested under a "report" key.
    report = output.get("report", {}) if isinstance(output.get("report"), dict) else {}

    content = (
        report.get("report_markdown")
        or output.get("report_markdown")
        or report.get("executive_summary")
        or output.get("executive_summary")
        or output.get("summary")
        or output.get("result")
    )
    if not content and output:
        import json

        content = json.dumps(output, indent=2, default=str)

    if not content:
        return

    title = (
        report.get("title")
        or output.get("title")
        or output.get("report_title")
        or f"{catalog_name} — output"
    )

    await artifact_svc.create_artifact(
        mission_id=mission_id,
        execution_record_id=execution_record_id,
        task_execution_id=task_execution_id,
        agent_id=agent_name,
        artifact_type=config.artifact_type or "report",
        title=title,
        content_text=content,
        content_type="markdown",
    )

    logger.info(
        "Artifact created",
        extra={
            "agent": agent_name,
            "artifact_type": config.artifact_type,
            "title": title[:80],
            "mission_id": mission_id,
        },
    )
