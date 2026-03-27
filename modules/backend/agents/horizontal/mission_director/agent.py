"""
Mission Director Agent.

Conversational delegate that manages the mission on behalf of the user.
Uses tools to query mission state (team, history, context, workflows)
and trigger actions (run objectives, run workflows).

Entry point:
    create_agent(model) — for registry/chat integration
"""

import json
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from modules.backend.agents.horizontal.mission_director.deps import MissionDirectorDeps
from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent(model: str | Model) -> Agent:
    """Create the Mission Director agent with all tools registered."""
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("horizontal", "mission_director")

    agent: Agent[MissionDirectorDeps, str] = Agent(
        model,
        system_prompt=system_prompt,
        deps_type=MissionDirectorDeps,
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

            return json.dumps({
                "name": mission.name,
                "description": mission.description,
                "brief": mission.brief,
                "status": mission.status if isinstance(mission.status, str) else mission.status.value,
                "gate_mode": mission.gate_mode,
                "budget_ceiling_usd": mission.budget_ceiling_usd,
                "owner_id": mission.owner_id,
                "created_at": str(mission.created_at),
            }, indent=2, default=str)
        except Exception as e:
            logger.error("get_mission_info failed", exc_info=True)
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
                team_list.append({
                    "agent_name": entry.agent_name,
                    "description": entry.description,
                    "agent_type": entry.agent_type,
                    "tools": entry.tools or [],
                    "keywords": entry.keywords or [],
                    "scope": entry.scope or {},
                    "enabled": entry.enabled,
                })

            return json.dumps(team_list, indent=2, default=str)
        except Exception as e:
            logger.error("list_team failed", exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_execution_history(
        ctx: RunContext[MissionDirectorDeps],
        limit: int = 10,
    ) -> str:
        """Get recent execution history: status, cost, objective, timestamps.

        Args:
            limit: Maximum number of executions to return (default 10).
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.execution import ExecutionService

            svc = ExecutionService(ctx.deps.db_session)
            executions, total = await svc.list_executions(
                mission_id=ctx.deps.mission_id,
                limit=limit,
            )

            results = []
            for ex in executions:
                results.append({
                    "id": str(ex.id),
                    "objective": ex.objective,
                    "status": ex.status if isinstance(ex.status, str) else ex.status.value,
                    "trigger_type": ex.trigger_type,
                    "total_cost_usd": ex.total_cost_usd,
                    "started_at": str(ex.started_at) if ex.started_at else None,
                    "completed_at": str(ex.completed_at) if ex.completed_at else None,
                    "result_summary": ex.result_summary,
                })

            return json.dumps({
                "executions": results,
                "total": total,
            }, indent=2, default=str)
        except Exception as e:
            logger.error("get_execution_history failed", exc_info=True)
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

            from modules.backend.services.execution import ExecutionService

            svc = ExecutionService(ctx.deps.db_session)
            ex = await svc.get_execution(execution_id)

            return json.dumps({
                "id": str(ex.id),
                "objective": ex.objective,
                "status": ex.status if isinstance(ex.status, str) else ex.status.value,
                "trigger_type": ex.trigger_type,
                "triggered_by": ex.triggered_by,
                "roster_ref": ex.roster_ref,
                "complexity_tier": ex.complexity_tier,
                "total_cost_usd": ex.total_cost_usd,
                "cost_ceiling_usd": ex.cost_ceiling_usd,
                "started_at": str(ex.started_at) if ex.started_at else None,
                "completed_at": str(ex.completed_at) if ex.completed_at else None,
                "result_summary": ex.result_summary,
                "execution_outcome": ex.execution_outcome,
                "error_data": ex.error_data,
            }, indent=2, default=str)
        except Exception as e:
            logger.error("get_execution_detail failed", exc_info=True)
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
            logger.error("get_mission_context failed", exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def list_workflows(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List available workflows that can be run against this mission."""
        try:
            from modules.backend.services.workflow import WorkflowService

            svc = WorkflowService()
            workflows = svc.list_workflows(enabled_only=True)

            results = []
            for wf in workflows:
                results.append({
                    "workflow_name": wf.workflow_name,
                    "description": wf.description,
                    "version": wf.version,
                    "trigger_type": wf.trigger.type if wf.trigger else None,
                    "budget_max_cost_usd": wf.budget.max_cost_usd if wf.budget else None,
                    "steps": len(wf.steps),
                })

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error("list_workflows failed", exc_info=True)
            return json.dumps({"error": str(e)})

    # ── Action Tools ──────────────────────────────────────

    @agent.tool
    async def run_objective(
        ctx: RunContext[MissionDirectorDeps],
        objective: str,
        budget_usd: float = 5.0,
    ) -> str:
        """Start an ad-hoc execution with the given objective.

        Creates the execution and starts it in the background. Returns
        the execution ID immediately — use get_execution_detail to
        check progress and results.

        Args:
            objective: What to accomplish (e.g., "run a health check").
            budget_usd: Maximum cost ceiling for this run (default $5.00).
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            import asyncio
            from modules.backend.services.execution import ExecutionService

            async with ExecutionService.factory() as svc:
                execution = await svc.create_adhoc_execution(
                    objective=objective,
                    triggered_by="mission_director",
                    cost_ceiling_usd=budget_usd,
                    mission_id=ctx.deps.mission_id,
                )
                execution_id = str(execution.id)

            # Run in background — don't block the chat
            async def _run_in_background():
                try:
                    async with ExecutionService.factory() as svc:
                        await svc.run_execution(execution_id)
                except Exception:
                    logger.error("Background execution failed", extra={"execution_id": execution_id})

            asyncio.create_task(_run_in_background())

            return json.dumps({
                "execution_id": execution_id,
                "status": "started",
                "objective": objective,
                "budget_usd": budget_usd,
                "message": "Execution started in background. Use get_execution_detail to check progress.",
            }, indent=2, default=str)
        except Exception as e:
            logger.error("run_objective failed", exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def run_workflow(
        ctx: RunContext[MissionDirectorDeps],
        workflow_name: str,
    ) -> str:
        """Start a named workflow against the current mission.

        Creates the workflow run and starts it in the background. Returns
        immediately — use get_execution_history to check progress.

        Args:
            workflow_name: The workflow identifier (e.g., "system.platform-audit.workflow").
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            import asyncio

            # Resolve mission_id -> mission.name (WorkflowRunService needs mission_name)
            from modules.backend.services.mission import MissionService

            mission_svc = MissionService(ctx.deps.db_session)
            mission = await mission_svc.get_mission(ctx.deps.mission_id)
            mission_name = mission.name

            # Run in background — don't block the chat
            async def _run_in_background():
                try:
                    from modules.backend.services.workflow_run import WorkflowRunService
                    async with WorkflowRunService.factory() as svc:
                        await svc.run_workflow(
                            workflow_name=workflow_name,
                            triggered_by="mission_director",
                            mission_name=mission_name,
                        )
                except Exception:
                    logger.error("Background workflow failed", extra={"workflow": workflow_name})

            asyncio.create_task(_run_in_background())

            return json.dumps({
                "workflow_name": workflow_name,
                "mission": mission_name,
                "status": "started",
                "message": "Workflow started in background. Use get_execution_history to check progress.",
            }, indent=2, default=str)
        except Exception as e:
            logger.error("run_workflow failed", exc_info=True)
            return json.dumps({"error": str(e)})

    # NOTE: Gate tools (approve_gate, reject_gate, get_pending_gates) are
    # deferred to Phase 2. Gates currently resolve inline during dispatch —
    # no async queue exists for out-of-band resolution.

    return agent
