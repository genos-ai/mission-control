"""
Tool: check_background_tasks

Status of background work for the mission: workflow design, executions
and anything else running out of band.
"""

from __future__ import annotations

from functools import partial

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import CompactResult, run_tool

_NO_TASKS_MESSAGE = "No background tasks found."


def _as_task(record) -> dict:
    """Shape one background task record for the model."""
    return {
        "execution_record_id": record.id,
        "task_type": record.task_type,
        # status may be the enum or an already-coerced string.
        "status": (record.status if isinstance(record.status, str) else record.status.value),
        "objective": record.objective_statement,
        "temporal_workflow_id": record.temporal_workflow_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


async def check_background_tasks(mission_id: str) -> dict | CompactResult:
    """Read active and recently completed background tasks.

    Takes no session: the persistence service opens its own via
    `factory()`, so this reads committed state rather than the
    Director's in-flight transaction.

    Args:
        mission_id: Mission whose background tasks to read.

    Returns:
        The tasks and their count, or a `CompactResult` carrying a
        message when there are none.
    """
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        records = await svc.list_background_tasks(mission_id)

    if not records:
        return CompactResult({"tasks": [], "message": _NO_TASKS_MESSAGE})

    tasks = [_as_task(record) for record in records]
    return {"tasks": tasks, "count": len(tasks)}


# ── Registry integration ─────────────────────────────────

_impl = check_background_tasks


def register(agent) -> None:
    """Register this tool on a PydanticAI agent."""

    @agent.tool
    async def check_background_tasks(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Check the status of background work (workflow design, executions, etc.).

        Returns all active (pending/running) and recently completed background
        tasks for this mission.
        """
        return await run_tool(
            ctx,
            "check_background_tasks",
            partial(_impl, ctx.deps.mission_id),
            # Opens its own session via the service factory, so the
            # Director's session may legitimately be absent.
            requires_session=False,
        )
