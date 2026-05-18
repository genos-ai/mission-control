"""Routing helpers — resolve which agent handles a message."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.backend.schemas.session import SessionResponse

from modules.backend.agents.mission_control.middleware import _load_mission_control_config
from modules.backend.agents.mission_control.models import MissionControlRequest
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.agents.mission_control.router import RuleBasedRouter
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def _resolve_agent(
    session: "SessionResponse",
    message: str,
    target_agent: str | None = None,
) -> str:
    """Determine which agent handles this message.

    Priority: explicit target_agent > session.agent_id > keyword routing > fallback.
    """
    registry = get_registry()

    if target_agent:
        if not registry.has(target_agent):
            available = ", ".join(c["agent_name"] for c in registry.list_all()) or "none"
            raise ValidationError(f"Unknown target agent: {target_agent}. Available: {available}.")
        return target_agent

    if session.agent_id and registry.has(session.agent_id):
        return session.agent_id

    router = RuleBasedRouter(registry)
    request = MissionControlRequest(user_input=message)
    agent_name = router.route(request)

    if agent_name is not None:
        return agent_name

    mc_config = _load_mission_control_config()
    fallback = mc_config.routing.fallback_agent
    if fallback and registry.has(fallback):
        return fallback

    available = ", ".join(c["agent_name"] for c in registry.list_all()) or "none"
    raise ValidationError(f"No agent matched. Available agents: {available}.")


def get_chat_agent() -> str:
    """Return the configured default agent for interactive chat sessions."""
    mc_config = _load_mission_control_config()
    return mc_config.routing.chat_agent
