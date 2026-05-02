"""Agent setup helpers — deps construction, usage limits, module imports."""

from __future__ import annotations

import importlib
from typing import Any

from pydantic_ai import UsageLimits

from modules.backend.agents.config_schema import AgentConfigSchema
from modules.backend.agents.deps.base import (
    BaseAgentDeps,
    FileScope,
    HealthAgentDeps,
    QaAgentDeps,
)
from modules.backend.agents.mission_control.middleware import _load_mission_control_config
from modules.backend.agents.mission_control.registry import get_registry
from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Shared httpx client for research agents. Module-level singleton avoids
# leaking a new connection pool on every agent invocation. Bounded pool
# prevents resource exhaustion during parallel searcher fan-out.
_research_http_client = None


def _get_research_http_client():
    """Get or create the shared httpx AsyncClient for research agents."""
    global _research_http_client
    if _research_http_client is None:
        import httpx
        _research_http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=30.0,
        )
    return _research_http_client


def build_deps_from_config(agent_config: AgentConfigSchema) -> dict[str, Any]:
    """Build common dep fields from agent YAML config."""
    scope = FileScope(
        read_paths=agent_config.scope.read,
        write_paths=agent_config.scope.write,
    )
    return {
        "project_root": find_project_root(),
        "scope": scope,
        "config": agent_config,
    }


def _build_agent_deps(
    agent_name: str,
    agent_config: AgentConfigSchema,
    session_id: str | None = None,
    mission_id: str | None = None,
    db_session: Any | None = None,
    event_bus: Any | None = None,
) -> BaseAgentDeps:
    """Build the appropriate deps dataclass for a given agent."""
    common = build_deps_from_config(agent_config)
    common["session_id"] = session_id
    category = agent_name.split(".")[0]

    if "mission.director" in agent_name:
        from modules.backend.agents.mission.director.deps import MissionDirectorDeps
        return MissionDirectorDeps(**common, mission_id=mission_id, db_session=db_session)
    if "platform.director" in agent_name:
        from modules.backend.agents.platform.director.deps import PlatformDirectorDeps
        return PlatformDirectorDeps(**common, db_session=db_session)
    if category == "platform" and "health" in agent_name:
        return HealthAgentDeps(**common, app_config=get_app_config())
    if category == "software":
        return QaAgentDeps(**common)
    if "mission.workflow" in agent_name:
        from modules.backend.agents.mission.workflow.deps import ArchitectAgentDeps
        return ArchitectAgentDeps(**common, mission_id=mission_id, db_session=db_session)
    if "mission.supervisor" in agent_name:
        from modules.backend.agents.mission.supervisor.deps import MissionSupervisorDeps
        return MissionSupervisorDeps(**common, mission_id=mission_id, db_session=db_session)
    if "mission.planning" in agent_name:
        from modules.backend.agents.mission.planning.agent import PlanningAgentDeps
        return PlanningAgentDeps(
            **common, mission_id=mission_id, db_session=db_session,
            event_bus=event_bus,
        )
    if "security.webapp.scanner" in agent_name:
        from modules.backend.agents.security.deps import ScanDeps
        from modules.backend.agents.security.tool_registry import SecurityToolRegistry
        from modules.backend.agents.security.config import get_security_assessment_config

        try:
            sec_config = get_security_assessment_config()
            tool_registry = SecurityToolRegistry(
                config_path=find_project_root() / sec_config.tool_registry_path
            )
        except Exception:
            logger.warning(
                "Failed to load security tool registry — scanner tools will be unavailable",
                extra={"agent_name": agent_name},
                exc_info=True,
            )
            tool_registry = None
            sec_config = None

        return ScanDeps(
            **common,
            tool_registry=tool_registry,
            security_config=sec_config,
            evidence_path="@workspace/evidence",
        )
    if category == "research":
        from modules.backend.agents.research.deps import ResearchAgentDeps
        return ResearchAgentDeps(**common, http_client=_get_research_http_client())

    return BaseAgentDeps(**common)


def _get_usage_limits(agent_name: str | None = None) -> UsageLimits:
    """Build UsageLimits, preferring per-agent overrides from agent.yaml.

    Resolution order:
        1. Per-agent max_tokens / max_requests from agent.yaml (if set)
        2. System defaults from mission_control.yaml limits
    """
    mc_config = _load_mission_control_config()
    system_tokens = mc_config.limits.max_tokens_per_task
    system_requests = mc_config.limits.max_requests_per_task

    if agent_name:
        try:
            agent_config = get_registry().get(agent_name)
            return UsageLimits(
                request_limit=agent_config.max_requests or system_requests,
                total_tokens_limit=agent_config.max_tokens or system_tokens,
            )
        except KeyError:
            logger.debug("Agent '%s' not in registry, using system limits", agent_name)

    return UsageLimits(
        request_limit=system_requests,
        total_tokens_limit=system_tokens,
    )


def _import_agent_module(agent_name: str) -> Any:
    """Dynamically import an agent module from the registry."""
    registry = get_registry()
    module_path = registry.resolve_module_path(agent_name)
    return importlib.import_module(module_path)
