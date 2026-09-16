"""
Tool: capture_mission_intent

Record a revised mission intent when the user's goals or scope shift.
"""

from __future__ import annotations

from pydantic_ai import RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps

_DEFAULT_REASON = "Scope change detected in conversation"


def build_scope(scope_in: list[str] | None, scope_out: list[str] | None) -> dict:
    """Assemble the scope payload, omitting empty sides.

    An absent or empty list is left out entirely rather than stored as
    `[]`, so "not stated" stays distinguishable from "explicitly empty".
    """
    scope: dict[str, list[str]] = {}
    if scope_in:
        scope["in"] = scope_in
    if scope_out:
        scope["out"] = scope_out
    return scope


async def capture_mission_intent(
    mission_id: str,
    session_id: str | None,
    intent: str,
    scope_in: list[str] | None = None,
    scope_out: list[str] | None = None,
    reason: str = _DEFAULT_REASON,
) -> str:
    """Record a revised intent for the mission.

    Args:
        mission_id: Mission whose intent changed.
        session_id: Transport session the change was observed in (P15).
        intent: The full current intent text.
        scope_in: What is in scope.
        scope_out: What is out of scope.
        reason: Why the intent changed.

    Returns:
        The adapter's own summary string, passed through unchanged.
    """
    from modules.backend.agents.adapters.intent import capture_intent

    return await capture_intent(
        mission_id=mission_id,
        intent=intent,
        scope=build_scope(scope_in, scope_out),
        reason=reason,
        session_id=session_id,
    )


# ── Registry integration ─────────────────────────────────

_impl = capture_mission_intent


def register(agent) -> None:
    """Register this tool on a PydanticAI agent.

    Does not use `run_tool`: the adapter already returns a formatted
    string, and this tool had no session guard and no try/except before
    extraction. Routing it through the shared scaffold would add both and
    would double-encode the result as JSON.
    """

    @agent.tool
    async def capture_mission_intent(
        ctx: RunContext[MissionDirectorDeps],
        intent: str,
        scope_in: list[str] | None = None,
        scope_out: list[str] | None = None,
        reason: str = _DEFAULT_REASON,
    ) -> str:
        """Capture a revised intent when the user's goals or scope change.

        Call this when the user narrows, expands, or reprioritises
        the mission scope. Not for every message — only when scope
        actually shifts.

        Args:
            intent: The full current intent text.
            scope_in: What's in scope (optional list of items).
            scope_out: What's out of scope (optional list of items).
            reason: Why the intent changed.
        """
        return await _impl(
            ctx.deps.mission_id,
            ctx.deps.session_id,
            intent,
            scope_in=scope_in,
            scope_out=scope_out,
            reason=reason,
        )
