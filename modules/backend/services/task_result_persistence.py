"""Persist one task result: its task_executions row, artifact and retry attempts.

Shared by the in-process path (agents/mission_control/persistence_bridge.py)
and the per-task activity path (services/run_task_execution.py). Imports
nothing from modules.backend.agents, so the service layer can call it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.backend.core.logging import get_logger
from modules.backend.schemas.execution_outcome import TaskResult, TaskStatus
from modules.backend.services.execution_persistence import ExecutionPersistenceService
from modules.backend.services.mission_artifact import MissionArtifactService

if TYPE_CHECKING:
    from modules.backend.models.execution_record import TaskExecution

logger = get_logger(__name__)


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
        failure=task_result.failure,
    )

    # Create artifact if the agent declares produces_artifact.
    # Driven by catalog config, not output heuristics.
    if artifact_svc is not None and mission_id is not None:
        try:
            # A savepoint, so a failed artifact insert rolls back alone and the
            # caller's transaction (the task row) can still commit.
            async with service.session.begin_nested():
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

    from modules.backend.core.agent_registry import get_registry

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
