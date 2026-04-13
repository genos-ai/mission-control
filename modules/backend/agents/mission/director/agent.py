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
                    logger.error("Background execution failed", extra={"execution_id": execution_id}, exc_info=True)

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

        Resolves workflow_name against mission-scoped workflows first,
        then system templates. Strips '.workflow' suffix if present.

        Args:
            workflow_name: The workflow identifier (e.g., "system.platform-audit" or
                          "system.platform-audit.workflow").
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            import asyncio

            mission_id = ctx.deps.mission_id

            # Strip .workflow suffix — DB stores names without it
            clean_name = workflow_name
            if clean_name.endswith(".workflow"):
                clean_name = clean_name[: -len(".workflow")]

            # Run in background — don't block the chat
            async def _run_in_background():
                try:
                    from modules.backend.services.workflow_run import WorkflowRunService
                    async with WorkflowRunService.factory() as svc:
                        await svc.run_workflow(
                            workflow_name=clean_name,
                            triggered_by="mission_director",
                            mission_id=mission_id,
                        )
                except Exception:
                    logger.error("Background workflow failed", extra={"workflow": workflow_name}, exc_info=True)

            asyncio.create_task(_run_in_background())

            return json.dumps({
                "workflow_name": clean_name,
                "mission_id": mission_id,
                "status": "started",
                "message": "Workflow started in background. Use get_execution_history to check progress.",
            }, indent=2, default=str)
        except Exception as e:
            logger.error("run_workflow failed", exc_info=True)
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
            logger.error("get_plan failed", exc_info=True)
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
            logger.error("refine_plan failed", exc_info=True)
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

        The architect will design the workflow steps, validate them,
        and save the workflow to the database. The user can then run
        it anytime via run_workflow or the Workflows tab.

        Args:
            name: Workflow name (e.g. 'ops.health-check').
            description: What the workflow does.
            instructions: Detailed instructions for the architect — what
                agents to use, what steps to include, what to check.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.agents.mission_control.helpers import (
                _build_model,
                assemble_instructions,
            )
            from modules.backend.agents.mission_control.registry import get_registry
            from modules.backend.agents.mission.workflow.deps import ArchitectAgentDeps
            from modules.backend.agents.deps.base import FileScope

            registry = get_registry()
            agent_config = registry.get("mission.workflow.agent")
            model = _build_model(agent_config.model)
            architect = registry.get_instance("mission.workflow.agent", model)

            scope = FileScope(
                read_paths=agent_config.scope.read,
                write_paths=agent_config.scope.write,
            )
            from modules.backend.core.config import find_project_root
            deps = ArchitectAgentDeps(
                project_root=find_project_root(),
                scope=scope,
                config=agent_config,
                session_id=ctx.deps.session_id,
                mission_id=ctx.deps.mission_id,
                db_session=ctx.deps.db_session,
            )

            prompt = (
                f"Design and save a workflow with these specifications:\n\n"
                f"Name: {name}\n"
                f"Description: {description}\n\n"
                f"Instructions:\n{instructions}\n\n"
                f"Use browse_catalog to check available agents, then "
                f"design the steps, validate with validate_workflow, "
                f"and save with save_workflow. Do NOT ask for confirmation — "
                f"the user already confirmed by requesting this."
            )

            result = await architect.run(prompt, deps=deps)
            return json.dumps({
                "status": "success",
                "workflow_name": name,
                "architect_response": str(result.output)[:500],
            })
        except Exception as e:
            logger.error("design_workflow failed", exc_info=True)
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
                        extra={"task_id": task_id, "error": str(e)},
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
            logger.error("approve_plan_tasks failed", exc_info=True)
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return json.dumps({"error": str(e)})

    # NOTE: Gate tools (approve_gate, reject_gate, get_pending_gates) are
    # deferred to Phase 2. Gates currently resolve inline during dispatch —
    # no async queue exists for out-of-band resolution.

    # Plan 52: Director followups are handled by Temporal — the
    # MissionRunWorkflow starts a ChatTurnWorkflow for the Director
    # when the supervisor decides ADVANCE_REFINE, PROPOSE_COMPLETE,
    # or ESCALATE. No schedule_followup tool needed.

    return agent
