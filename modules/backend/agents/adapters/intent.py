"""
Intent Tools — pure function implementations (P7).

Used by the Director agent to capture and retrieve mission intent.
Thin wrappers registered as @agent.tool in the Director's agent.py.
"""

from modules.backend.core.logging import get_logger
from modules.backend.models.mission_intent import IntentSource

logger = get_logger(__name__)


async def capture_intent(
    mission_id: str,
    intent: str,
    scope: dict | None = None,
    reason: str = "Scope change detected in conversation",
    session_id: str | None = None,
    agent_id: str = "mission.director.agent",
) -> str:
    """Capture a new intent revision for the mission.

    Called by the Director when the user's scope changes.
    Returns the intent ID or a dedup message.
    """
    from modules.backend.services.mission_intent import MissionIntentService

    async with MissionIntentService.factory() as svc:
        result = await svc.create_intent(
            mission_id,
            intent,
            scope=scope or {},
            source=IntentSource.DIRECTOR_INFERRED.value,
            reason=reason,
            agent_id=agent_id,
            session_id=session_id,
        )

    if result is None:
        return "Intent unchanged (identical to current)."

    logger.info(
        "Intent captured by Director",
        extra={"mission_id": mission_id, "intent_id": result.id},
    )
    return f"Intent updated: {result.intent_summary}"


async def restate_current_intent(mission_id: str) -> str:
    """Retrieve the current intent for the mission.

    Called by the Director to check the current scope before responding.
    Returns a formatted string for injection into the conversation.
    """
    from modules.backend.services.mission_intent import MissionIntentService

    async with MissionIntentService.factory() as svc:
        current = await svc.get_current(mission_id)

    if current is None:
        return "No intent set for this mission."

    parts = [f"Current intent: {current.intent}"]
    if current.scope:
        in_scope = current.scope.get("in", [])
        out_scope = current.scope.get("out", [])
        if in_scope:
            parts.append(f"In scope: {', '.join(in_scope)}")
        if out_scope:
            parts.append(f"Out of scope: {', '.join(out_scope)}")
    parts.append(f"(set {current.source}, reason: {current.reason})")

    return "\n".join(parts)
