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
    execution_record_id: str | None = None,
) -> str | None:
    """Persist execution results. Best-effort — does not raise.

    Returns the ExecutionRecord id on success, or None if persistence
    failed (best-effort semantics preserved).

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
        artifact_svc = (
            MissionArtifactService(db_session) if mission_id else None
        )

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
                task_plan_json=task_plan_json,
                execution_outcome_json=outcome.model_dump(),
                planning_thinking_trace=thinking_trace,
                total_cost_usd=outcome.total_cost_usd,
            )
        else:
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

        # Plan 40: persist research reports from research_loop tasks
        if mission_id:
            await _persist_research_reports(
                db_session=db_session,
                mission_id=mission_id,
                execution_record_id=record.id,
                task_results=outcome.task_results,
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


async def _persist_research_reports(
    *,
    db_session: "AsyncSession",
    mission_id: str,
    execution_record_id: str,
    task_results: list,
) -> None:
    """Persist research reports from research_loop task results (Plan 40).

    Best-effort — failures are logged but never block execution persistence.
    Detects research loop tasks by agent_name starting with "research(".
    """
    from modules.backend.services.research_report import ResearchReportService

    svc = ResearchReportService(db_session)

    for task_result in task_results:
        if not getattr(task_result, "agent_name", "").startswith("research("):
            continue

        output = getattr(task_result, "output_reference", None)
        if not isinstance(output, dict):
            continue

        report_data = output.get("report")
        if not isinstance(report_data, dict):
            continue

        try:
            await svc.create_report(
                mission_id=mission_id,
                execution_id=execution_record_id,
                query=report_data.get("title", output.get("report_title", "")),
                report_markdown=report_data.get("report_markdown", ""),
                report_structured={
                    "sections": report_data.get("sections", []),
                    "executive_summary": report_data.get("executive_summary", ""),
                    "methodology": report_data.get("methodology", ""),
                    "limitations": report_data.get("limitations", ""),
                },
                sources=report_data.get("sources", []),
                metadata_json={
                    "total_sources": output.get("total_sources", 0),
                    "total_iterations": output.get("total_iterations", 0),
                    "total_findings": output.get("total_findings", 0),
                    "coverage_ratio": output.get("coverage_ratio", 0),
                },
                status="verified" if output.get("verification_score") else "draft",
                citation_count=len(report_data.get("sources", [])),
                verification_score=output.get("verification_score"),
            )
            logger.info(
                "Research report persisted",
                extra={"mission_id": mission_id, "title": report_data.get("title", "")[:80]},
            )
        except Exception:
            logger.warning(
                "Failed to persist research report (non-fatal)",
                extra={"mission_id": mission_id, "task_id": getattr(task_result, "task_id", "")},
                exc_info=True,
            )
