"""Shared helper used by every Director tool module.

Split out of agent.py (Plan 84 Phase 5.3). Lives in its own module (not
agent.py) so the tool sibling modules (tools_mission, tools_plan,
tools_workflow, tools_knowledge) can import it without a circular
import back to agent.py, which itself imports the tool modules'
register functions.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.core.logging import get_logger
from modules.backend.events.types import SystemEvent

logger = get_logger(__name__)


class ToolRefusal(Exception):
    """An expected refusal, reported to the LLM as an error payload.

    Distinct from a failure. A refusal means the tool was called with
    input it will not act on (a missing reason, a gate mode that forbids
    auto-approval), so there is nothing to log, emit or roll back. The
    LLM is expected to read the message and adjust.
    """

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


async def _emit_tool_failure(
    ctx: RunContext[MissionDirectorDeps],
    tool_name: str,
    exc: Exception,
) -> None:
    """Mission event so a failed Director tool call is visible in the
    Console — not just in the tool's own JSON error return to the LLM,
    which the user may never see relayed verbatim in chat."""
    if not ctx.deps.event_bus or not ctx.deps.mission_id:
        return
    session_id = uuid.UUID(ctx.deps.session_id) if ctx.deps.session_id else uuid.uuid4()
    await _emit(
        ctx.deps.event_bus,
        SystemEvent,
        session_id=session_id,
        source=f"director:{tool_name}",
        level="error",
        message=f"{tool_name} failed: {exc}"[:500],
        mission_id=ctx.deps.mission_id,
    )


async def run_tool(
    ctx: RunContext[MissionDirectorDeps],
    tool_name: str,
    operation: Callable[[], Awaitable[dict]],
    *,
    indent: int | None = 2,
    rollback_on_error: bool = False,
) -> str:
    """Run a tool implementation and serialise its result for the LLM.

    Holds the scaffold every Director tool shares: the missing-session
    guard, JSON serialisation, error logging, failure event emission and
    optional rollback. `operation` is a zero-argument callable (use
    `functools.partial`) so implementations keep explicit parameters and
    stay callable without a `RunContext` (P7).

    Args:
        ctx: The PydanticAI run context, for deps and event emission.
        tool_name: Name used in log records and the failure event.
        operation: The implementation call to run.
        indent: `json.dumps` indent for a successful result. Refusals and
            errors are never indented, matching the pre-refactor output.
        rollback_on_error: Roll the session back on failure. Set for tools
            that write before they can fail.
    """
    if ctx.deps.db_session is None:
        return json.dumps({"error": "No database session available"})

    try:
        result = await operation()
        return json.dumps(result, indent=indent, default=str)
    except ToolRefusal as refusal:
        return json.dumps({"error": refusal.message, **refusal.details})
    except Exception as exc:
        logger.error(
            f"{tool_name} failed",
            extra={"mission_id": ctx.deps.mission_id},
            exc_info=True,
        )
        await _emit_tool_failure(ctx, tool_name, exc)
        if rollback_on_error:
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                logger.debug(f"db rollback failed after {tool_name} error", exc_info=True)
        return json.dumps({"error": str(exc)})
