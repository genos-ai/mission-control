"""Shared helper used by every Director tool module.

Split out of agent.py (Plan 84 Phase 5.3). Lives in its own module (not
agent.py) so the tool sibling modules (tools_mission, tools_plan,
tools_workflow, tools_knowledge) can import it without a circular
import back to agent.py, which itself imports the tool modules'
register functions.
"""

from __future__ import annotations

import uuid

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission_control.helpers import _emit
from modules.backend.events.types import SystemEvent


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
