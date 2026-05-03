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

from modules.backend.agents.platform.director.deps import PlatformDirectorDeps
from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(model: str | Model, tool_names: list[str] | None = None) -> Agent:
    """Create the Platform Director agent with platform-scoped tools."""
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("platform", "director")

    agent: Agent[PlatformDirectorDeps, str] = Agent(
        model,
        system_prompt=system_prompt,
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

        from modules.backend.repositories.mission import MissionRepository
        from modules.backend.services.execution_persistence import ExecutionPersistenceService

        mission_repo = MissionRepository(db)
        exec_svc = ExecutionPersistenceService(db)

        missions = await mission_repo.list_all()
        recent_runs, total = await exec_svc.list_executions(limit=10)

        return {
            "active_missions": len(missions),
            "recent_executions": total,
            "missions": [
                {"name": m.name, "status": m.status, "tier": m.tier}
                for m in missions[:10]
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

        from modules.backend.repositories.mission import MissionRepository

        repo = MissionRepository(db)
        missions = await repo.list_all(limit=50)

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

        from sqlalchemy import func, select
        from modules.backend.models.execution_record import ExecutionRecord

        result = await db.execute(
            select(
                ExecutionRecord.mission_id,
                func.sum(ExecutionRecord.total_cost_usd).label("total_cost"),
                func.count(ExecutionRecord.id).label("execution_count"),
            ).group_by(ExecutionRecord.mission_id)
        )
        rows = result.all()

        return {
            "mission_costs": [
                {
                    "mission_id": str(row.mission_id) if row.mission_id else "unscoped",
                    "total_cost_usd": float(row.total_cost or 0),
                    "execution_count": row.execution_count,
                }
                for row in rows
            ],
            "platform_total_usd": sum(float(r.total_cost or 0) for r in rows),
        }

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
            "redis": "connected" if getattr(config.database, 'redis', None) else "not configured",
            "temporal_enabled": config.temporal.enabled if hasattr(config, 'temporal') and config.temporal else False,
            "max_concurrent_missions": getattr(config.workflows, 'max_concurrent_missions', 0) if hasattr(config, 'workflows') else 0,
        }

    return agent
