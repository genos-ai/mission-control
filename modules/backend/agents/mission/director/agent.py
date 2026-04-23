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

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission_control.helpers import (
    _build_model,
    assemble_instructions,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


# ── Plan 56 Phase B: Tool Fork Helpers ──────────────────────────────────


async def _create_background_record(
    *,
    mission_id: str,
    session_id: str,
    task_type: str,
    objective: str,
    params: dict,
) -> Any:
    """Create an ExecutionRecord for a background task via the service layer."""
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        record = await svc.create_background_record(
            mission_id=mission_id,
            session_id=session_id,
            task_type=task_type,
            objective=objective,
            params=params,
        )
        record_id = record.id

    # Return a lightweight ref — the ORM instance is detached after commit
    class _Ref:
        def __init__(self, id: str):
            self.id = id
    return _Ref(record_id)


async def _start_tool_fork_workflow(
    *,
    workflow_name: str,
    input_data: Any,
    record_id: str,
) -> str:
    """Start a Temporal workflow for a forked tool call. Returns workflow ID."""
    import uuid
    from modules.backend.temporal.client import get_temporal_client, get_temporal_config
    from modules.backend.temporal.tool_fork_workflow import (
        DesignWorkflowWorkflow,
        RunWorkflowWorkflow,
    )

    workflow_map = {
        "DesignWorkflowWorkflow": DesignWorkflowWorkflow.run,
        "RunWorkflowWorkflow": RunWorkflowWorkflow.run,
    }

    run_method = workflow_map[workflow_name]
    client = await get_temporal_client()
    config = get_temporal_config()

    workflow_id = f"tool-fork-{workflow_name.lower()}-{record_id[:12]}-{uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        run_method,
        input_data,
        id=workflow_id,
        task_queue=config.task_queue,
    )

    # Update the record with the temporal workflow ID
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    async with ExecutionPersistenceService.factory() as svc:
        record = await svc.get_execution(record_id)
        if record is not None:
            record.temporal_workflow_id = workflow_id

    return workflow_id


async def _schedule_director_followup(
    *,
    db_session,
    session_id: str | None,
    mission_id: str | None,
    trigger_event_types: list[str],
    prompt_template: str,
) -> None:
    """Schedule a session followup so the Director wakes on a future event.

    Best-effort — failures are logged but never block the calling tool.
    Used by approve_plan_tasks to ensure the Director
    proactively reports outcomes to the user (Plan 51 Phase E).
    """
    if db_session is None or session_id is None:
        return
    try:
        from modules.backend.agents.tools.followup import schedule_followup

        await schedule_followup(
            db_session,
            session_id=session_id,
            mission_id=mission_id,
            trigger_event_types=trigger_event_types,
            prompt_template=prompt_template,
            created_by_agent="mission.director.agent",
        )
    except Exception:
        logger.warning(
            "Director followup scheduling failed (non-fatal)",
            extra={"session_id": session_id, "mission_id": mission_id},
            exc_info=True,
        )


async def _ensure_research_team(db_session, mission_id: str) -> None:
    """Add research agents to mission team if not already present.

    Research agents must be in the team for derive_roster_from_team() to
    include them. Idempotent — skips agents already in the team.
    """
    if db_session is None:
        return
    try:
        from modules.backend.repositories.agent_catalog import AgentCatalogRepository
        from modules.backend.repositories.mission_team import MissionTeamRepository

        RESEARCH_AGENTS = [
            "research.strategist.agent",
            "research.searcher.agent",
            "research.analyst.agent",
            "research.synthesizer.agent",
            "research.verifier.agent",
        ]
        team_repo = MissionTeamRepository(db_session)
        catalog_repo = AgentCatalogRepository(db_session)

        for agent_name in RESEARCH_AGENTS:
            catalog_entry = await catalog_repo.get_by_name(agent_name)
            if not catalog_entry:
                continue
            existing = await team_repo.get_by_mission_and_agent(
                mission_id, catalog_entry.id
            )
            if existing is None:
                await team_repo.create(
                    mission_id=mission_id,
                    agent_catalog_id=catalog_entry.id,
                )
                logger.debug(
                    "Added research agent to mission team",
                    extra={"agent": agent_name, "mission_id": mission_id},
                )
        await db_session.flush()
    except Exception:
        logger.warning(
            "Failed to ensure research team (non-fatal)",
            extra={"mission_id": mission_id},
            exc_info=True,
        )


def create_agent(model: str | Model) -> Agent:
    """Create the Mission Director agent with all tools registered."""
    if isinstance(model, str):
        model = _build_model(model)

    system_prompt = assemble_instructions("mission", "director")

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
            logger.error("get_mission_info failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
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
                    "interface": entry.interface,
                    "constraints": entry.constraints or {},
                    "enabled": entry.enabled,
                    "chat_enabled": entry.chat_enabled,
                })

            return json.dumps(team_list, indent=2, default=str)
        except Exception as e:
            logger.error("list_team failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
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
            for agent in all_agents:
                searchable = (
                    (agent.description or "").lower()
                    + " ".join(agent.keywords or []).lower()
                    + (agent.agent_name or "").lower()
                )
                if keyword and keyword.lower() not in searchable:
                    continue
                results.append({
                    "agent_name": agent.agent_name,
                    "description": agent.description,
                    "agent_type": agent.agent_type,
                    "enabled": agent.enabled,
                    "on_team": agent.agent_name in team_names,
                    "keywords": agent.keywords or [],
                    "tools": agent.tools or [],
                    "scope": agent.scope or {},
                    "interface": agent.interface,
                    "constraints": agent.constraints or {},
                    "chat_enabled": agent.chat_enabled,
                })

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error("browse_catalog failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
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
            logger.error("get_execution_history failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
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
            logger.error("get_execution_detail failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
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
            logger.error("get_mission_context failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def list_workflows(ctx: RunContext[MissionDirectorDeps]) -> str:
        """List available workflows (mission-scoped + system templates)."""
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.workflow_definition import WorkflowDefinitionService

            svc = WorkflowDefinitionService(ctx.deps.db_session)

            # Mission-scoped workflows
            mission_wfs = await svc.list_workflows(ctx.deps.mission_id, enabled_only=True)
            # System templates
            system_wfs = await svc.list_workflows(None, enabled_only=True)

            results = []
            seen_names: set[str] = set()

            for wf in mission_wfs:
                seen_names.add(wf.name)
                results.append({
                    "name": wf.name,
                    "description": wf.description,
                    "version": wf.version,
                    "trigger_type": wf.trigger_type,
                    "step_count": wf.step_count,
                    "scope": "mission",
                })

            for wf in system_wfs:
                if wf.name in seen_names:
                    continue  # Mission-scoped takes precedence
                results.append({
                    "name": wf.name,
                    "description": wf.description,
                    "version": wf.version,
                    "trigger_type": wf.trigger_type,
                    "step_count": wf.step_count,
                    "scope": "system",
                })

            return json.dumps(results, indent=2, default=str)
        except Exception as e:
            logger.error("list_workflows failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    # ── Action Tools ──────────────────────────────────────

    @agent.tool
    async def run_workflow(
        ctx: RunContext[MissionDirectorDeps],
        workflow_name: str,
    ) -> str:
        """Start a named workflow against the current mission.

        Creates an execution record and starts a durable Temporal workflow
        in the background. Returns immediately — use check_background_tasks
        to check progress.

        Resolves workflow_name against mission-scoped workflows first,
        then system templates. Strips '.workflow' suffix if present.

        Args:
            workflow_name: The workflow identifier (e.g., "system.platform-audit" or
                          "system.platform-audit.workflow").
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            mission_id = ctx.deps.mission_id

            # Strip .workflow suffix — DB stores names without it
            clean_name = workflow_name
            if clean_name.endswith(".workflow"):
                clean_name = clean_name[: -len(".workflow")]

            record = await _create_background_record(
                mission_id=mission_id,
                session_id=ctx.deps.session_id,
                task_type="run_workflow",
                objective=f"Run workflow: {clean_name}",
                params={"workflow_name": clean_name},
            )

            from modules.backend.temporal.tool_fork_models import RunWorkflowInput
            workflow_id = await _start_tool_fork_workflow(
                workflow_name="RunWorkflowWorkflow",
                input_data=RunWorkflowInput(
                    mission_id=mission_id,
                    session_id=ctx.deps.session_id,
                    execution_record_id=record.id,
                    workflow_name=clean_name,
                ),
                record_id=record.id,
            )

            return json.dumps({
                "execution_record_id": record.id,
                "temporal_workflow_id": workflow_id,
                "workflow_name": clean_name,
                "mission_id": mission_id,
                "status": "started_in_background",
                "message": "Workflow started in background. Check progress via check_background_tasks.",
            }, indent=2, default=str)
        except Exception as e:
            logger.error("run_workflow failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    # ── Research Tools (Plan 40) ────────────────────────────────────

    @agent.tool
    async def start_research(
        ctx: RunContext[MissionDirectorDeps],
        query: str,
        depth: str = "comprehensive",
        include_domains: list[str] | None = None,
    ) -> str:
        """Start a deep research investigation on any topic.

        Triggers the research workflow template which runs 5 specialized
        agents (strategist, searcher, analyst, synthesizer, verifier) in
        an iterative search loop. Returns immediately — research runs in
        the background.

        Args:
            query: The research question to investigate.
            depth: Research depth — "quick" (2-5 min), "moderate" (5-15 min),
                   or "comprehensive" (15-30 min).
            include_domains: Only search these domains (e.g. ["anthropic.com", "openai.com"]).
                            If not set, searches the entire web.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            mission_id = ctx.deps.mission_id

            # Ensure research agents are in the mission team
            await _ensure_research_team(ctx.deps.db_session, mission_id)

            record = await _create_background_record(
                mission_id=mission_id,
                session_id=ctx.deps.session_id,
                task_type="research",
                objective=f"Deep research: {query}",
                params={"query": query, "depth": depth},
            )

            from modules.backend.temporal.tool_fork_models import RunWorkflowInput
            workflow_id = await _start_tool_fork_workflow(
                workflow_name="RunWorkflowWorkflow",
                input_data=RunWorkflowInput(
                    mission_id=mission_id,
                    session_id=ctx.deps.session_id,
                    execution_record_id=record.id,
                    workflow_name="research.deep-research",
                    context_overrides={
                        "query": query,
                        "research_depth": depth,
                        **({"include_domains": include_domains} if include_domains else {}),
                    },
                ),
                record_id=record.id,
            )

            await _schedule_director_followup(
                db_session=ctx.deps.db_session,
                session_id=ctx.deps.session_id,
                mission_id=mission_id,
                trigger_event_types=["research.completed", "research.failed"],
                prompt_template=(
                    "The research just completed. Check the results and "
                    "report back to the user with key findings."
                ),
            )

            return json.dumps({
                "status": "research_started",
                "execution_record_id": record.id,
                "temporal_workflow_id": workflow_id,
                "depth": depth,
                "message": f"Research started: \"{query}\". I'll report back when it's done.",
            }, indent=2, default=str)

        except Exception as e:
            logger.error("start_research failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def get_research_findings(
        ctx: RunContext[MissionDirectorDeps],
        report_id: str | None = None,
    ) -> str:
        """Get research findings for this mission.

        Returns the executive summary, key findings, source count, and
        verification score from the latest research report (or a specific
        report by ID). Use this to answer follow-up questions about
        completed research.

        Args:
            report_id: Optional specific report ID. If None, returns the
                       latest report for this mission.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.research_report import ResearchReportService
            svc = ResearchReportService(ctx.deps.db_session)

            if report_id:
                report = await svc.get_report(report_id)
            else:
                reports = await svc.list_for_mission(
                    ctx.deps.mission_id, limit=1
                )
                report = reports[0] if reports else None

            if report is None:
                return json.dumps({
                    "status": "no_reports",
                    "message": "No research reports found for this mission.",
                })

            structured = report.report_structured or {}
            return json.dumps({
                "report_id": report.id,
                "query": report.query,
                "status": report.status,
                "executive_summary": structured.get("executive_summary", ""),
                "source_count": len(report.sources or []),
                "citation_count": report.citation_count,
                "verification_score": report.verification_score,
                "report_markdown_preview": (report.report_markdown or "")[:2000],
                "sources": (report.sources or [])[:10],
            }, indent=2, default=str)

        except Exception as e:
            logger.error("get_research_findings failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def run_objective(
        ctx: RunContext[MissionDirectorDeps],
        objective: str,
    ) -> str:
        """Run an objective via the plan path (Plan 62). Async dispatch.

        Args:
            objective: What to accomplish (natural language).
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            mission_id = ctx.deps.mission_id

            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan import MissionPlanService
            acting_user_id = (await MissionService(ctx.deps.db_session).get_mission(mission_id)).owner_id
            svc = MissionPlanService(ctx.deps.db_session)
            result = await svc.run_objective(
                mission_id=mission_id,
                objective=objective,
                user_id=acting_user_id,
                session_id=ctx.deps.session_id,
            )
            await ctx.deps.db_session.commit()

            # Schedule followup so Director wakes when supervisor decides
            if result.get("outcome_status") == "dispatching":
                await _schedule_director_followup(
                    ctx.deps.db_session,
                    session_id=ctx.deps.session_id,
                    mission_id=mission_id,
                    trigger_event_types=["mission_plan.supervisor_decision"],
                    prompt_template=(
                        "The supervisor just evaluated the latest run. "
                        "Check the plan status and report back to the user."
                    ),
                )

            return json.dumps(result, default=str)

        except Exception as e:
            logger.error("run_objective failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                pass
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
                tasks.append({
                    "execution_record_id": r.id,
                    "task_type": r.task_type,
                    "status": r.status if isinstance(r.status, str) else r.status.value,
                    "objective": r.objective_statement,
                    "temporal_workflow_id": r.temporal_workflow_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                })

            return json.dumps({"tasks": tasks, "count": len(tasks)}, indent=2, default=str)
        except Exception as e:
            logger.error("check_background_tasks failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    # ── Mission Plan Tools (Plan 42) ──────────────────────────────────

    @agent.tool
    async def get_plan(ctx: RunContext[MissionDirectorDeps]) -> str:
        """Read the current mission plan — the long-lived backlog.

        Returns the plan body (TaskPlan JSON), per-task status for every
        task in the plan, the current autonomy mode, and cumulative
        budget. Use this before calling refine_plan so you can reason
        about what already exists rather than starting from scratch, and
        to answer questions like "what's in the plan?" or "what tasks
        are approved?"

        The plan is created lazily — if no refinement has happened yet,
        task_plan_json will be null and task_states will be empty.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.agents.tools.plan_introspection import get_plan_state

            result = await get_plan_state(
                ctx.deps.db_session, mission_id=ctx.deps.mission_id,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error("get_plan failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def refine_plan(
        ctx: RunContext[MissionDirectorDeps],
        instructions: str,
    ) -> str:
        """Refine the mission plan via the Planning Agent.

        Delegates to the Planning Agent — you do NOT author TaskPlans
        yourself. The Planning Agent receives the current plan + your
        instructions and produces a new TaskPlan that incorporates the
        user's requested changes while preserving task_id strings for
        unchanged tasks (so existing approvals and run history survive).

        Use this when the user describes what they want to work on,
        asks for a new plan, or asks to modify the existing plan. Pass
        the user's instructions in their own words — the Planning Agent
        works best with concrete, specific language.

        After refinement completes, tell the user which tasks were
        added or changed, and prompt them to review in the Plan tab.
        The user approves tasks before they run — you do NOT dispatch
        tasks from here. Dispatch is the user's explicit action.

        Args:
            instructions: Natural-language refinement request from the
                user. Example: "Split the test phase into unit and
                integration. Add a final task that posts the results
                to Slack."
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan import MissionPlanService

            mission_svc = MissionService(ctx.deps.db_session)
            mission = await mission_svc.get_mission(ctx.deps.mission_id)

            svc = MissionPlanService(ctx.deps.db_session)
            plan = await svc.get_or_create_plan(ctx.deps.mission_id)
            refined = await svc.refine(
                plan.id,
                instructions,
                user_id=mission.owner_id,
            )
            await ctx.deps.db_session.commit()

            task_count = (
                len(refined.task_plan_json.get("tasks", []))
                if refined.task_plan_json
                else 0
            )

            return json.dumps({
                "plan_id": refined.id,
                "version": refined.version,
                "task_count": task_count,
                "gate_mode": refined.gate_mode,
                "tasks": [
                    {
                        "task_id": t.get("task_id"),
                        "agent": t.get("agent"),
                        "description": t.get("description"),
                        "dependencies": t.get("dependencies", []),
                    }
                    for t in (refined.task_plan_json.get("tasks", []) if refined.task_plan_json else [])
                ],
                "message": (
                    f"Plan refined to v{refined.version} with {task_count} tasks. "
                    "Ask the user to review and approve in the Plan tab."
                ),
            }, indent=2, default=str)
        except Exception as e:
            logger.error("refine_plan failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            # Roll back the (failed) refinement transaction so the
            # session is in a clean state for the next tool call.
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return json.dumps({"error": str(e)})

    @agent.tool
    async def design_workflow(
        ctx: RunContext[MissionDirectorDeps],
        name: str,
        description: str,
        instructions: str,
    ) -> str:
        """Delegate workflow design to the Workflow Architect agent.

        Starts the Architect in a durable Temporal workflow and returns
        immediately. The user sees progress in the stream tab. Use
        check_background_tasks to check completion.

        Args:
            name: Workflow name (e.g. 'ops.health-check').
            description: What the workflow does.
            instructions: Detailed instructions for the architect — what
                agents to use, what steps to include, what to check.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            record = await _create_background_record(
                mission_id=ctx.deps.mission_id,
                session_id=ctx.deps.session_id,
                task_type="design_workflow",
                objective=f"Design workflow: {name}",
                params={"name": name, "description": description, "instructions": instructions},
            )

            from modules.backend.temporal.tool_fork_models import DesignWorkflowInput
            workflow_id = await _start_tool_fork_workflow(
                workflow_name="DesignWorkflowWorkflow",
                input_data=DesignWorkflowInput(
                    mission_id=ctx.deps.mission_id,
                    session_id=ctx.deps.session_id,
                    execution_record_id=record.id,
                    workflow_name=name,
                    description=description,
                    instructions=instructions,
                ),
                record_id=record.id,
            )

            return json.dumps({
                "execution_record_id": record.id,
                "temporal_workflow_id": workflow_id,
                "status": "started_in_background",
                "workflow_name": name,
                "message": f"The Workflow Architect is designing '{name}'. "
                           "You'll see progress in the stream tab. "
                           "Use check_background_tasks to check completion.",
            }, indent=2, default=str)
        except Exception as e:
            logger.error("design_workflow failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            return json.dumps({"error": str(e)})

    @agent.tool
    async def approve_plan_tasks(
        ctx: RunContext[MissionDirectorDeps],
        task_ids: list[str],
        reason: str,
    ) -> str:
        """Auto-approve plan tasks on the user's behalf (ai_assisted /
        autonomous modes only — Plan 42 §10.4).

        Refuses when the plan is in `interactive` mode. In that mode the
        user has explicitly opted into approving every task themselves,
        and you must NOT bypass them. Tell the user to flip the plan
        to `ai_assisted` if they want you to auto-approve.

        The service's transitive dependency walk still runs — approving
        one task auto-approves its upstream dependencies if they were
        in `proposed` state. The returned transitioned_task_ids list
        reflects the full closure.

        When you call this tool, always explain WHY you are approving
        these tasks in the `reason` string. In `ai_assisted` mode this
        reason is surfaced to the user as part of the veto window UI
        (Phase 4b will wire the window itself; for now the reason is
        recorded in the tool log).

        Args:
            task_ids: List of task_id strings to approve. Each is
                approved individually via the service — if any task_id
                is not in the plan or is not in `proposed` state, it
                is silently skipped.
            reason: Short natural-language explanation of why you are
                approving these tasks. Must be 1-500 characters.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            if not reason or not reason.strip():
                return json.dumps({
                    "error": "reason is required — explain why you are approving",
                })
            if len(reason) > 500:
                return json.dumps({
                    "error": f"reason too long ({len(reason)} chars, max 500)",
                })

            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan import MissionPlanService

            mission_svc = MissionService(ctx.deps.db_session)
            mission = await mission_svc.get_mission(ctx.deps.mission_id)

            svc = MissionPlanService(ctx.deps.db_session)
            plan = await svc.get_or_create_plan(ctx.deps.mission_id)

            # Gate policy: refuse in interactive mode
            if plan.gate_mode == "interactive" or plan.gate_mode is None:
                return json.dumps({
                    "error": (
                        "Plan is in interactive mode — the user approves "
                        "tasks manually. Tell them to switch the plan to "
                        "ai_assisted if they want you to auto-approve on "
                        "their behalf."
                    ),
                    "gate_mode": plan.gate_mode,
                })

            if plan.gate_mode not in ("ai_assisted", "autonomous"):
                return json.dumps({
                    "error": f"Unsupported gate_mode for auto-approval: {plan.gate_mode}",
                })

            # The Director acts on behalf of the mission owner — use the
            # owner's user id so the plan_task_states.approved_by_user_id
            # FK is satisfied and the audit trail correctly attributes
            # the approval to a real user (not to an agent name).
            acting_user_id = mission.owner_id

            all_transitioned: list[str] = []
            for task_id in task_ids:
                try:
                    transitioned = await svc.approve_task(
                        plan.id, task_id, user_id=acting_user_id,
                    )
                    all_transitioned.extend(s.task_id for s in transitioned)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "approve_plan_tasks: skipping task",
                        extra={"task_id": task_id, "error": str(e), "mission_id": ctx.deps.mission_id},
                    )
            await ctx.deps.db_session.commit()

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_transitioned = [
                t for t in all_transitioned
                if not (t in seen or seen.add(t))
            ]

            logger.info(
                "Director auto-approved plan tasks",
                extra={
                    "plan_id": plan.id,
                    "requested_task_ids": task_ids,
                    "transitioned_task_ids": unique_transitioned,
                    "gate_mode": plan.gate_mode,
                    "reason": reason,
                },
            )

            # Schedule a followup so we wake when the supervisor decides
            # and proactively report to the user (Plan 51 Phase E).
            if unique_transitioned:
                await _schedule_director_followup(
                    db_session=ctx.deps.db_session,
                    session_id=ctx.deps.session_id,
                    mission_id=ctx.deps.mission_id,
                    trigger_event_types=["mission_plan.supervisor_decision"],
                    prompt_template=(
                        "The tasks I approved have been dispatched and the "
                        "supervisor just decided: {action}. Reason: {reason}. "
                        "Summarise the outcome for the user and suggest "
                        "next steps."
                    ),
                )

            return json.dumps({
                "plan_id": plan.id,
                "gate_mode": plan.gate_mode,
                "requested_task_ids": task_ids,
                "transitioned_task_ids": unique_transitioned,
                "reason": reason,
                "message": (
                    f"Auto-approved {len(unique_transitioned)} task(s) "
                    f"(including transitive dependencies). The user can "
                    f"still veto by rejecting any task in the Plan tab."
                ),
            }, indent=2, default=str)
        except Exception as e:
            logger.error("approve_plan_tasks failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True)
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return json.dumps({"error": str(e)})

    # NOTE: Gate tools (approve_gate, reject_gate, get_pending_gates) are
    # deferred to Phase 2. Gates currently resolve inline during dispatch —
    # no async queue exists for out-of-band resolution.

    # Plan 51 Phase E: Director followups are scheduled automatically
    # by approve_plan_tasks via _schedule_director_followup.
    # The Temporal path also wakes the Director via ChatTurnWorkflow.
    # Both paths ensure the Director proactively reports to the user.

    # ── Intent Tools (Plan 57 Phase C) ─────────────────────

    @agent.tool
    async def capture_mission_intent(
        ctx: RunContext[MissionDirectorDeps],
        intent: str,
        scope_in: list[str] | None = None,
        scope_out: list[str] | None = None,
        reason: str = "Scope change detected in conversation",
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
        from modules.backend.agents.tools.intent import capture_intent
        scope = {}
        if scope_in:
            scope["in"] = scope_in
        if scope_out:
            scope["out"] = scope_out
        return await capture_intent(
            mission_id=ctx.deps.mission_id,
            intent=intent,
            scope=scope,
            reason=reason,
            session_id=ctx.deps.session_id,
        )

    @agent.tool
    async def get_current_mission_intent(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Retrieve the current mission intent and scope."""
        from modules.backend.agents.tools.intent import restate_current_intent
        return await restate_current_intent(ctx.deps.mission_id)

    # ── Knowledge Query Tool (Plan 57 Phase D) ──────────────

    @agent.tool
    async def query_knowledge(
        ctx: RunContext[MissionDirectorDeps],
        query: str,
        domain_tags: list[str] | None = None,
        kinds: list[str] | None = None,
        platform_only: bool = False,
    ) -> str:
        """Search the knowledge platform for relevant learnings, decisions, and milestones.

        Use this to check "has anyone encountered this before?" before
        spending tokens on discovery. Returns matching entries with
        confidence scores and recommendations.

        Args:
            query: Free-text search query.
            domain_tags: Filter by domain tags (e.g. ["auth", "testing"]).
            kinds: Filter by kind (learning, decision, milestone).
            platform_only: Only search platform-promoted entries.
        """
        from modules.backend.agents.tools.knowledge import knowledge_query
        return await knowledge_query(
            ctx.deps.mission_id,
            query=query,
            kinds=kinds,
            domain_tags=domain_tags,
            platform_only=platform_only,
        )

    # ── Runtime Context Injection (Plan 57 Phase C) ────────

    @agent.instructions
    async def inject_current_intent(
        ctx: RunContext[MissionDirectorDeps],
    ) -> str:
        """Inject the current intent into every Director turn."""
        from modules.backend.agents.tools.intent import restate_current_intent
        try:
            intent_text = await restate_current_intent(ctx.deps.mission_id)
            if intent_text and "No intent set" not in intent_text:
                return f"\n[Mission Intent]\n{intent_text}\n"
        except Exception:
            pass
        return ""

    return agent
