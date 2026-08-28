"""
Platform Director Agent.

Admin-only conversational agent for platform operations. Provides
cross-mission visibility, cost analytics, system health status,
and infrastructure management.

Entry point:
    create_agent(model) — for registry/chat integration
"""

from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.mission_control.helpers import _build_model, assemble_instructions
from modules.backend.agents.platform.director.deps import PlatformDirectorDeps
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(model: str | Model, tool_names: list[str] | None = None) -> Agent:
    """Create the Platform Director agent with platform-scoped tools."""
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("platform", "director")

    agent: Agent[PlatformDirectorDeps, str] = Agent(
        model,
        instructions=system_prompt,
        deps_type=PlatformDirectorDeps,
    )

    @agent.tool
    async def get_platform_status(
        ctx: RunContext[PlatformDirectorDeps],
    ) -> dict[str, Any]:
        """Get overall platform health and status."""
        db = ctx.deps.db_session
        if not db:
            return {"error": "No database session available"}

        from modules.backend.services.execution_persistence import ExecutionPersistenceService
        from modules.backend.services.mission import MissionService

        mission_svc = MissionService(db)
        exec_svc = ExecutionPersistenceService(db)

        missions = await mission_svc.list_missions(include_archived=True)
        recent_runs, total = await exec_svc.list_executions(limit=10)

        return {
            "active_missions": len(missions),
            "recent_executions": total,
            "missions": [
                {"name": m.name, "status": m.status, "tier": m.tier} for m in missions[:10]
            ],
        }

    @agent.tool
    async def list_all_missions(
        ctx: RunContext[PlatformDirectorDeps],
    ) -> list[dict[str, Any]]:
        """List all missions across the platform (not scoped to one mission)."""
        db = ctx.deps.db_session
        if not db:
            return [{"error": "No database session available"}]

        from modules.backend.services.mission import MissionService

        missions = await MissionService(db).list_missions(include_archived=True, limit=50)

        return [
            {
                "id": str(m.id),
                "name": m.name,
                "description": m.description[:100],
                "status": m.status,
                "tier": m.tier,
                "owner_id": m.owner_id,
            }
            for m in missions
        ]

    @agent.tool
    async def get_cross_mission_costs(
        ctx: RunContext[PlatformDirectorDeps],
    ) -> dict[str, Any]:
        """Get cost breakdown across all missions."""
        db = ctx.deps.db_session
        if not db:
            return {"error": "No database session available"}

        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        return await ExecutionPersistenceService(db).get_cross_mission_cost_breakdown()

    @agent.tool
    async def get_system_agent_status(
        ctx: RunContext[PlatformDirectorDeps],
    ) -> list[dict[str, str]]:
        """List system (dispatch infrastructure) agents and their status."""
        from modules.backend.agents.mission_control.registry import get_registry

        registry = get_registry()
        return registry.list_system()

    @agent.tool
    async def get_platform_config(
        ctx: RunContext[PlatformDirectorDeps],
    ) -> dict[str, Any]:
        """Get platform configuration summary (non-sensitive)."""
        from modules.backend.core.config import get_app_config

        config = get_app_config()
        return {
            "database": "connected" if config.database else "not configured",
            "redis": "connected" if getattr(config.database, "redis", None) else "not configured",
            "temporal_enabled": (
                config.temporal.enabled
                if hasattr(config, "temporal") and config.temporal
                else False
            ),
            "max_concurrent_missions": (
                getattr(config.workflows, "max_concurrent_missions", 0)
                if hasattr(config, "workflows")
                else 0
            ),
        }

    return agent
