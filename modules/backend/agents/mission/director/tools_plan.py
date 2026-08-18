"""Director tools: mission plan read/refine/approve and objective execution.

Split out of agent.py (Plan 84 Phase 5.3). Pure move, no behavior change.
"""

from __future__ import annotations

import json

from pydantic_ai import Agent, RunContext

from modules.backend.agents.mission.director.deps import MissionDirectorDeps
from modules.backend.agents.mission.director.tool_helpers import _emit_tool_failure
from modules.backend.agents.mission.director.tools_workflow import (
    _schedule_director_followup,
)
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def register_plan_tools(agent: Agent) -> None:
    """Register mission plan read/refine/approve/dispatch tools."""

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
        the tasks relationship will be empty.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            from modules.backend.agents.adapters.plan_introspection import get_plan_state

            result = await get_plan_state(
                ctx.deps.db_session,
                mission_id=ctx.deps.mission_id,
            )
            return json.dumps(result, indent=2, default=str)
        except Exception as e:
            logger.error(
                "get_plan failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "get_plan", e)
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

        This starts a PlanRefineWorkflow via Temporal and returns
        immediately. The workflow emits mission_plan.refined via SSE
        on completion — the frontend and console pick it up
        automatically. Tell the user their plan is being generated
        and they can watch progress in the Plan tab.

        Args:
            instructions: Natural-language refinement request from the
                user. Example: "Split the test phase into unit and
                integration. Add a final task that posts the results
                to Slack."
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            import uuid as _uuid

            from modules.backend.core.config import get_app_config, get_default_budget_usd
            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan import MissionPlanService
            from modules.backend.temporal.client import get_temporal_client
            from modules.backend.temporal.plan_refine_models import PlanRefineInput
            from modules.backend.temporal.plan_refine_workflow import PlanRefineWorkflow

            mission_id = ctx.deps.mission_id
            mission = await MissionService(ctx.deps.db_session).get_mission(mission_id)
            plan_svc = MissionPlanService(ctx.deps.db_session)
            plan = await plan_svc.get_or_create_plan(mission_id)
            await ctx.deps.db_session.commit()

            # Start PlanRefineWorkflow — the Temporal activity handles
            # its own DB session, event bus, commit, and error reporting.
            # No ORM objects accessed after this point.
            client = await get_temporal_client()
            config = get_app_config().temporal
            workflow_id = f"plan-refine-{plan.id[:12]}-{_uuid.uuid4().hex[:8]}"

            await client.start_workflow(
                PlanRefineWorkflow.run,
                PlanRefineInput(
                    mission_id=mission_id,
                    plan_id=plan.id,
                    instructions=instructions,
                    user_id=mission.owner_id,
                    mission_budget_usd=plan.budget_usd_ceiling or get_default_budget_usd(),
                ),
                id=workflow_id,
                task_queue=config.task_queue,
            )

            logger.info(
                "Director started PlanRefineWorkflow",
                extra={
                    "mission_id": mission_id,
                    "plan_id": plan.id,
                    "workflow_id": workflow_id,
                },
            )

            return json.dumps(
                {
                    "status": "refining",
                    "plan_id": plan.id,
                    "workflow_id": workflow_id,
                    "message": (
                        "Plan refinement started. The Planning Agent is building "
                        "tasks now — progress is visible in the Console and Plan "
                        "tab. Tell the user to watch the Plan tab for new tasks."
                    ),
                },
                indent=2,
                default=str,
            )

        except Exception as e:
            logger.error(
                "refine_plan failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "refine_plan", e)
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
                return json.dumps(
                    {
                        "error": "reason is required — explain why you are approving",
                    }
                )
            if len(reason) > 500:
                return json.dumps(
                    {
                        "error": f"reason too long ({len(reason)} chars, max 500)",
                    }
                )

            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan import MissionPlanService

            mission_svc = MissionService(ctx.deps.db_session)
            mission = await mission_svc.get_mission(ctx.deps.mission_id)

            svc = MissionPlanService(ctx.deps.db_session)
            plan = await svc.get_or_create_plan(ctx.deps.mission_id)

            # Gate policy: refuse in interactive mode
            if plan.gate_mode == "interactive" or plan.gate_mode is None:
                return json.dumps(
                    {
                        "error": (
                            "Plan is in interactive mode — the user approves "
                            "tasks manually. Tell them to switch the plan to "
                            "ai_assisted if they want you to auto-approve on "
                            "their behalf."
                        ),
                        "gate_mode": plan.gate_mode,
                    }
                )

            if plan.gate_mode not in ("ai_assisted", "autonomous"):
                return json.dumps(
                    {
                        "error": f"Unsupported gate_mode for auto-approval: {plan.gate_mode}",
                    }
                )

            # The Director acts on behalf of the mission owner — use the
            # owner's user id so the tasks.approved_by_user_id
            # FK is satisfied and the audit trail correctly attributes
            # the approval to a real user (not to an agent name).
            acting_user_id = mission.owner_id

            all_transitioned: list[str] = []
            for task_id in task_ids:
                try:
                    transitioned = await svc.approve_task(
                        plan.id,
                        task_id,
                        user_id=acting_user_id,
                    )
                    all_transitioned.extend(s.id for s in transitioned)
                except Exception as e:
                    # best-effort — non-fatal, this task is simply skipped; the
                    # aggregate outcome is already reported accurately via
                    # transitioned_task_ids in the tool's own JSON return below.
                    logger.warning(
                        "approve_plan_tasks: skipping task",
                        extra={
                            "task_id": task_id,
                            "error": str(e),
                            "mission_id": ctx.deps.mission_id,
                        },
                    )

            # Save plan attributes before commit — commit() expires all
            # ORM attributes and any access triggers MissingGreenlet.
            _plan_id = plan.id
            _gate_mode = plan.gate_mode
            await ctx.deps.db_session.commit()

            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_transitioned = [t for t in all_transitioned if not (t in seen or seen.add(t))]

            logger.info(
                "Director auto-approved plan tasks",
                extra={
                    "plan_id": _plan_id,
                    "requested_task_ids": task_ids,
                    "transitioned_task_ids": unique_transitioned,
                    "gate_mode": _gate_mode,
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

            return json.dumps(
                {
                    "plan_id": _plan_id,
                    "gate_mode": _gate_mode,
                    "requested_task_ids": task_ids,
                    "transitioned_task_ids": unique_transitioned,
                    "reason": reason,
                    "message": (
                        f"Auto-approved {len(unique_transitioned)} task(s) "
                        f"(including transitive dependencies). The user can "
                        f"still veto by rejecting any task in the Plan tab."
                    ),
                },
                indent=2,
                default=str,
            )
        except Exception as e:
            logger.error(
                "approve_plan_tasks failed",
                extra={"mission_id": ctx.deps.mission_id},
                exc_info=True,
            )
            await _emit_tool_failure(ctx, "approve_plan_tasks", e)
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("db rollback failed after approve_plan_tasks error", exc_info=True)
            return json.dumps({"error": str(e)})

    # NOTE: Gate tools (approve_gate, reject_gate, get_pending_gates) are
    # deferred to Phase 2. Gates currently resolve inline during dispatch —
    # no async queue exists for out-of-band resolution.

    # Plan 51 Phase E: Director followups are scheduled automatically
    # by approve_plan_tasks via _schedule_director_followup.
    # The Temporal path also wakes the Director via ChatTurnWorkflow.
    # Both paths ensure the Director proactively reports to the user.

    @agent.tool
    async def run_objective(
        ctx: RunContext[MissionDirectorDeps],
        objective: str,
    ) -> str:
        """Execute an objective end-to-end: plan tasks, approve, and dispatch.

        Use this when the user wants something DONE — research, scans,
        code tasks, analysis. The Planning Agent decomposes the objective
        into a task DAG based on the team's capabilities, auto-approves
        (if gate mode permits), and dispatches via Temporal. Returns
        immediately — you are notified when execution completes.

        Do NOT use this for planning-only requests (use refine_plan instead).

        Args:
            objective: What to accomplish (natural language). Be specific —
                include scope, constraints, and any user-specified details.
        """
        try:
            if ctx.deps.db_session is None:
                return json.dumps({"error": "No database session available"})

            mission_id = ctx.deps.mission_id

            from modules.backend.services.mission import MissionService
            from modules.backend.services.mission_plan_orchestrator import MissionPlanOrchestrator

            acting_user_id = (
                await MissionService(ctx.deps.db_session).get_mission(mission_id)
            ).owner_id
            svc = MissionPlanOrchestrator(ctx.deps.db_session, event_bus=ctx.deps.event_bus)
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
            logger.error(
                "run_objective failed", extra={"mission_id": ctx.deps.mission_id}, exc_info=True
            )
            await _emit_tool_failure(ctx, "run_objective", e)
            try:
                await ctx.deps.db_session.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("db rollback failed after run_objective error", exc_info=True)
            return json.dumps({"error": str(e)})
