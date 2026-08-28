"""
Session followup tool (Plan 51 Phase A).

Pure function for the ``schedule_followup`` agent tool. The agent's
PydanticAI wrapper lives in the agent module that registers the
tool (e.g. Director, Supervisor); this file is the service-layer
adapter that takes a db session and delegates to
``SessionFollowupService``.

Same convention as ``tools/workflow_design.py``: tools accept a db
session + structured args, return a dict, and never depend on
PydanticAI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.services.session_followup import (
    DEFAULT_EXPIRES_IN_SECONDS,
    SessionFollowupService,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def schedule_followup(
    session: AsyncSession,
    *,
    session_id: str,
    mission_id: str | None,
    trigger_event_types: list[str],
    prompt_template: str,
    created_by_agent: str,
    trigger_filter: dict[str, Any] | None = None,
    expires_in_seconds: int = DEFAULT_EXPIRES_IN_SECONDS,
) -> dict[str, Any]:
    """Register a followup for the calling agent.

    The agent calls this when it wants to continue the conversation
    on a future event — e.g. "I've dispatched the run; wake me when
    it completes so I can summarise for the user". The followup is
    scoped to the agent's current session and fires one turn.

    Returns a result dict with either a ``followup_id`` (success) or
    an ``error`` (validation failure). Never raises — the tool is
    designed to be called from a PydanticAI ``@agent.tool`` wrapper
    that cannot cleanly surface Python exceptions to the LLM.

    Validation failures render as a readable error string the agent
    can reason about ("you exceeded the per-session followup cap").

    v1 intentionally hardcodes ``max_fires = 1`` and
    ``cooldown_seconds = 0`` — multi-fire followups are deferred
    until a concrete use case lands.
    """
    try:
        svc = SessionFollowupService(session)
        row = await svc.schedule_followup(
            session_id=session_id,
            mission_id=mission_id,
            trigger_event_types=trigger_event_types,
            trigger_filter=trigger_filter,
            prompt_template=prompt_template,
            created_by_agent=created_by_agent,
            expires_in_seconds=expires_in_seconds,
            max_fires=1,
            cooldown_seconds=0,
        )
        return {
            "ok": True,
            "followup_id": row.id,
            "expires_at": row.expires_at.isoformat(),
            "trigger_event_types": list(row.trigger_event_types or []),
        }
    except ValidationError as exc:
        logger.info(
            "schedule_followup validation error",
            extra={
                "session_id": session_id,
                "agent": created_by_agent,
                "error": str(exc),
            },
        )
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        # best-effort — this pure function has no event_bus (called from
        # multiple agents with different deps shapes); the caller already
        # gets the error back in the returned dict and its own tool
        # wrapper decides whether to surface it further.
        logger.error(
            "schedule_followup unexpected error",
            extra={
                "session_id": session_id,
                "agent": created_by_agent,
                "error": str(exc),
                "mission_id": mission_id,
            },
            exc_info=True,
        )
        return {
            "ok": False,
            "error": f"unexpected error: {exc}",
        }
