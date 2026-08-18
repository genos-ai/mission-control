"""Director tools: mission/team/catalog introspection and background-task status.

Split out of agent.py (Plan 84 Phase 5.3). Pure move, no behavior change.
"""

from __future__ import annotations

import json

from pydantic_ai import Agent, RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import _emit_tool_failure
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def register_mission_tools(agent: Agent) -> None:
    """Register mission/team/catalog/history introspection tools."""

    # ── Self-introspection ──────────────────────────────────

    @agent.tool
    async def list_tools(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List all tools available to you. Call this when unsure what
        tools you have or before attempting an action you're not sure
        you can perform. You can ONLY use tools listed here."""
        # Tool names are collected after all @agent.tool registrations
        # and stored on the _registered_tools attribute by create_agent.
        tools = getattr(list_tools, "_registered_tools", [])
        return json.dumps(
            {
                "available_tools": len(tools),
                "tools": tools,
                "note": "You can ONLY call tools in this list. Do not invent tool names.",
            },
            indent=2,
        )

    # ── Read Tools ────────────────────────────────────────

    @agent.tool
    async def get_mission_info(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Get current mission details: name, description, brief, gate mode, budget."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.mission import MissionService

            svc = MissionService(ctx.deps.db_session)
            mission = await svc.get_mission(ctx.deps.mission_id)

            return json.dumps(
                {
                    "name": mission.name,
                    "description": mission.description,
                    "brief": mission.brief,
                    "status": (
                        mission.status if isinstance(mission.status, str) else mission.status.value
                    ),
                    "gate_mode": mission.gate_mode,
                    "budget_ceiling_usd": mission.budget_ceiling_usd,
                    "owner_id": mission.owner_id,
                    "created_at": str(mission.created_at),
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            logger.error(
                "get_mission_info failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "get_mission_info", e)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def list_team(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List all agents on the mission team with their capabilities, tools, and access scope."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.repositories.agent_catalog import AgentCatalogRepository
            from modules.backend.services.mission_team import MissionTeamService

            team_svc = MissionTeamService(ctx.deps.db_session)
            catalog_repo = AgentCatalogRepository(ctx.deps.db_session)

            members = await team_svc.list_team(ctx.deps.mission_id)
            team_list = []
            for member in members:
                entry = await catalog_repo.get_by_id_or_none(member.agent_catalog_id)
                if not entry:
                    continue
                team_list.append(
                    {
                        "agent_name": entry.agent_name,
                        "description": entry.description,
                        "agent_type": entry.agent_type,
                        "tools": entry.tools or [],
                        "keywords": entry.keywords or [],
                        "scope": entry.scope or {},
                        "interface": entry.interface,
                        "constraints": entry.constraints or {},
                        "enabled": entry.enabled,
                        "chat_enabled": entry.chat_enabled,
                    }
                )

            return json.dumps(team_list, indent=2, default=str)
        except Exception as e:
            logger.error(
                "list_team failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "list_team", e)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def browse_catalog(
        ctx: RunContext[MissionDirectorDeps],
        keyword: str | None = None,
    ) -> str:
        """Browse the full agent catalog to see what agents are available.

        Use this to discover agents that are NOT on the current mission
        team. If a needed agent is in the catalog but not on the team,
        suggest the user adds it via the Team tab or 'mc team add'.

        Args:
            keyword: Optional search keyword to filter by capabilities.

        Returns:
            JSON array of all catalog agents with name, type, description,
            enabled status, and whether they're on the current team.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.repositories.agent_catalog import AgentCatalogRepository
            from modules.backend.services.mission_team import MissionTeamService

            catalog_repo = AgentCatalogRepository(ctx.deps.db_session)
            team_svc = MissionTeamService(ctx.deps.db_session)

            # Get all catalog entries
            all_agents = await catalog_repo.get_all(limit=200)
            # Get current team for comparison
            members = await team_svc.list_team(ctx.deps.mission_id)
            team_names = set()
            for m in members:
                entry = await catalog_repo.get_by_id_or_none(m.agent_catalog_id)
                if entry:
                    team_names.add(entry.agent_name)

            results = []
            for agent_entry in all_agents:
                searchable = (
                    (agent_entry.description or "").lower()
                    + " ".join(agent_entry.keywords or []).lower()
                    + (agent_entry.agent_name or "").lower()
                )
                if keyword and keyword.lower() not in searchable:
                    continue
                results.append(
                    {
                        "agent_name": agent_entry.agent_name,
                        "description": agent_entry.description,
                        "agent_type": agent_entry.agent_type,
                        "enabled": agent_entry.enabled,
                        "on_team": agent_entry.agent_name in team_names,
                        "keywords": agent_entry.keywords or [],
                        "tools": agent_entry.tools or [],
                        "scope": agent_entry.scope or {},
                        "interface": agent_entry.interface,
                        "constraints": agent_entry.constraints or {},
                        "chat_enabled": agent_entry.chat_enabled,
                    }
                )

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error(
                "browse_catalog failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "browse_catalog", e)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_execution_history(
        ctx: RunContext[MissionDirectorDeps],
        limit: int = 10,
    ) -> str:
        """Get recent execution history: status, cost, objective, timestamps.

        Queries both execution_records (plan dispatches, research, workflows)
        and live in-flight executions for a unified view of all runs.

        Args:
            limit: Maximum number of executions to return (default 10).
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.execution_persistence import ExecutionPersistenceService

            svc = ExecutionPersistenceService(ctx.deps.db_session)
            runs, total = await svc.list_all_runs(
                mission_id=ctx.deps.mission_id,
                limit=limit,
            )

            return json.dumps(
                {
                    "executions": runs,
                    "total": total,
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            logger.error(
                "get_execution_history failed",
                extra={"mission_id": ctx.deps.mission_id},
                exc_info=True,
            )
            await _emit_tool_failure(ctx, "get_execution_history", e)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_execution_detail(
        ctx: RunContext[MissionDirectorDeps],
        execution_id: str,
    ) -> str:
        """Get full detail for a specific execution including task results.

        Args:
            execution_id: The UUID of the execution to inspect.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.execution_persistence import ExecutionPersistenceService

            svc = ExecutionPersistenceService(ctx.deps.db_session)
            record = await svc.get_execution(execution_id)
            if record:
                status = (
                    record.status.value if hasattr(record.status, "value") else str(record.status)
                )
                return json.dumps(
                    {
                        "id": str(record.id),
                        "objective": record.objective_statement,
                        "status": status,
                        "roster_name": record.roster_name,
                        "total_cost_usd": record.total_cost_usd,
                        "cost_ceiling_usd": record.cost_ceiling_usd,
                        "started_at": str(record.started_at) if record.started_at else None,
                        "completed_at": str(record.completed_at) if record.completed_at else None,
                        "execution_outcome": record.execution_outcome_json,
                        "workflow_run_id": record.workflow_run_id,
                        "workflow_step_id": record.workflow_step_id,
                    },
                    indent=2,
                    default=str,
                )

            return json.dumps({"error": f"Execution '{execution_id}' not found"})
        except Exception as e:
            logger.error(
                "get_execution_detail failed",
                extra={"mission_id": ctx.deps.mission_id},
                exc_info=True,
            )
            await _emit_tool_failure(ctx, "get_execution_detail", e)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_mission_context(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Get the Mission Context Document (MCD) -- strategic context for the mission."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.mission_context import MissionContextManager

            manager = MissionContextManager(ctx.deps.db_session)
            context = await manager.get_context(ctx.deps.mission_id)

            if not context:
                return json.dumps({"message": "No mission context document found."})

            return json.dumps(context, indent=2, default=str)
        except Exception as e:
            logger.error(
                "get_mission_context failed",
                extra={"mission_id": ctx.deps.mission_id},
                exc_info=True,
            )
            await _emit_tool_failure(ctx, "get_mission_context", e)
            return json.dumps({"error": str(e)})

    # ── Background Task Tracking (Plan 56 Phase B) ─────────────────────

    @agent.tool
    async def check_background_tasks(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Check the status of background work (workflow design, executions, etc.).

        Returns all active (pending/running) and recently completed background
        tasks for this mission.
        """
        try:
            from modules.backend.services.execution_persistence import ExecutionPersistenceService

            async with ExecutionPersistenceService.factory() as svc:
                records = await svc.list_background_tasks(ctx.deps.mission_id)

            if not records:
                return json.dumps({"tasks": [], "message": "No background tasks found."})

            tasks = []
            for r in records:
                tasks.append(
                    {
                        "execution_record_id": r.id,
                        "task_type": r.task_type,
                        "status": r.status if isinstance(r.status, str) else r.status.value,
                        "objective": r.objective_statement,
                        "temporal_workflow_id": r.temporal_workflow_id,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    }
                )

            return json.dumps({"tasks": tasks, "count": len(tasks)}, indent=2, default=str)
        except Exception as e:
            logger.error(
                "check_background_tasks failed",
                extra={"mission_id": ctx.deps.mission_id},
                exc_info=True,
            )
            await _emit_tool_failure(ctx, "check_background_tasks", e)
            return json.dumps({"error": str(e)})
