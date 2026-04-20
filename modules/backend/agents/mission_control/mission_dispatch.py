"""Mission dispatch — multi-agent mission execution (Plan 13).

Extracted from mission_control.py (Plan 38 §2.1). Contains
handle_mission(), the entry point for complex multi-agent runs
with planning, validation, environment provisioning, and dispatch.

Public: handle_mission().
"""

import uuid
from typing import Any

from modules.backend.agents.mission_control.dispatch import dispatch
from modules.backend.agents.mission_control.gate import GateReviewer
from modules.backend.agents.mission_control.helpers import (
    _build_planning_prompt,
    _build_roster_prompt,
    _append_validation_feedback,
    _call_planning_agent,
    _make_agent_executor,
    _publish,
)
from modules.backend.agents.mission_control.models import EventBusProtocol, NoOpEventBus
from modules.backend.agents.mission_control.outcome import ExecutionOutcome, ExecutionStatus
from modules.backend.agents.mission_control.persistence_bridge import persist_mission_results
from modules.backend.agents.mission_control.plan_validator import validate_plan
from modules.backend.agents.mission_control.roster import derive_roster_from_team
from modules.backend.core.logging import get_logger
from modules.backend.core.protocols import SessionServiceProtocol
from modules.backend.events.types import (
    AgentResponseCompleteEvent,
    AgentThinkingEvent,
    PlanningPhaseEvent,
)
from modules.backend.schemas.task_plan import TaskPlan
from modules.backend.services.context_assembler import ContextAssembler
from modules.backend.services.context_curator import ContextCurator
from modules.backend.services.history_query import HistoryQueryService
from modules.backend.services.mission_context import MissionContextManager

logger = get_logger(__name__)


async def handle_mission(
    mission_run_id: str,
    mission_brief: str,
    *,
    session_service: SessionServiceProtocol,
    event_bus: EventBusProtocol = NoOpEventBus(),
    roster_name: str = "default",
    mission_budget_usd: float = 10.0,
    upstream_context: dict | None = None,
    session_id: str | None = None,
    mission_id: str | None = None,
    db_session: Any | None = None,
    gate: GateReviewer | None = None,
    execution_mode: str = "local",
    precomputed_plan: TaskPlan | None = None,
    mission_repo_root: str | None = None,
    prior_outputs: dict[str, dict] | None = None,
) -> ExecutionOutcome:
    """Dispatch entry point for complex multi-agent missions.

    1. Load roster
    2. Either call the Planning Agent for task decomposition OR use the
       caller-supplied `precomputed_plan` when provided (Plan 42: MissionPlan
       dispatch)
    3. Validate TaskPlan against all 11 rules
    4. Execute dispatch loop
    5. Return ExecutionOutcome

    Simple requests continue through handle() from Plan 12.
    Complex requests (explicit mission_brief or matched workflow) route here.

    When `precomputed_plan` is passed, the Planning Agent retry loop is
    skipped — the caller is responsible for producing a valid TaskPlan.
    The plan still flows through validate_plan before dispatch so the
    same 11 rules apply.
    """
    if not mission_id or not db_session:
        raise ValueError(
            "mission_id and db_session are required for dispatch. "
            "Agents are resolved from the mission team in the database."
        )

    _plan_sid = uuid.UUID(session_id) if session_id else uuid.uuid4()

    async def _phase(step: str, message: str) -> None:
        await _publish(event_bus, PlanningPhaseEvent(
            session_id=_plan_sid, source="mission_control",
            step=step, message=message,
        ))

    await _phase("roster", "Deriving agent roster from team")
    roster = await derive_roster_from_team(mission_id, db_session)
    roster_description = _build_roster_prompt(roster)
    await _phase("roster", f"Roster ready — {len(roster.agents)} agents")

    # Create context services BEFORE planning so the planner gets PCD + history
    context_curator = None
    context_assembler = None
    project_context = None
    recent_failures = None

    if mission_id and db_session:
        pcd_manager = MissionContextManager(db_session)
        context_curator = ContextCurator(pcd_manager)
        history_service = HistoryQueryService(db_session)

        from modules.backend.core.config import find_project_root
        from modules.backend.services.code_map.loader import CodeMapLoader

        code_map_loader = CodeMapLoader(find_project_root())
        context_assembler = ContextAssembler(
            context_manager=pcd_manager,
            history_service=history_service,
            code_map_loader=code_map_loader,
        )

        # Load project context for the planner (non-fatal)
        await _phase("context", "Loading mission context")
        try:
            project_context = await context_curator.get_mission_context(mission_id)
        except (OSError, ValueError, RuntimeError):
            logger.warning(
                "Failed to load PCD for planning (non-fatal)",
                extra={"mission_id": mission_id},
                exc_info=True,
            )

        # Load recent failures so the planner can avoid repeating them
        try:
            recent_failures = await history_service.get_recent_failures(
                mission_id, limit=5,
            )
        except (OSError, ValueError, RuntimeError):
            logger.warning(
                "Failed to load failure history for planning (non-fatal)",
                extra={"mission_id": mission_id},
                exc_info=True,
            )
        await _phase("context", "Context assembled")

    # Build planning prompt WITH project context
    planning_prompt = _build_planning_prompt(
        mission_brief=mission_brief,
        mission_id=mission_run_id,
        roster_description=roster_description,
        upstream_context=upstream_context,
        project_context=project_context,
        recent_failures=recent_failures,
    )

    # Either use the caller-supplied precomputed plan (Plan 42 dispatch path)
    # or call the Planning Agent with a retry loop (standard path).
    plan = None
    thinking_trace = None
    last_error = ""
    planning_agent_id = "system.planning.agent"

    if precomputed_plan is not None:
        # Plan 42: MissionPlanService dispatched an approved subset.
        await _phase("planning", "Using precomputed plan from MissionPlan")
        plan = precomputed_plan
        validation = validate_plan(plan, roster, mission_budget_usd)
        if not validation.is_valid:
            last_error = "; ".join(validation.errors)
            logger.warning(
                "Precomputed plan failed validation: %s",
                last_error,
                extra={
                    "mission_id": mission_id or mission_run_id,
                    "errors": validation.errors,
                },
            )
            plan = None
    else:
        max_planning_attempts = 3

        # Emit planning started event
        await _phase("thinking", "Planning agent decomposing objective")
        await _publish(event_bus, AgentThinkingEvent(
            session_id=_plan_sid,
            source="mission_control",
            agent_id=planning_agent_id,
        ))

        for attempt in range(max_planning_attempts):
            try:
                planning_result = await _call_planning_agent(
                    planning_prompt, roster, upstream_context,
                    event_bus=event_bus, session_id=session_id,
                )
                thinking_trace = planning_result.get("thinking_trace")

                plan = TaskPlan.model_validate(planning_result["task_plan"])

                validation = validate_plan(plan, roster, mission_budget_usd)
                if validation.is_valid:
                    break

                last_error = "; ".join(validation.errors)
                await _phase("error", f"Attempt {attempt + 1} failed: plan validation — {last_error}")
                logger.warning(
                    "TaskPlan validation failed, retrying Planning Agent",
                    extra={
                        "attempt": attempt + 1,
                        "errors": validation.errors,
                        "mission_id": mission_run_id,
                    },
                )
                planning_prompt = _append_validation_feedback(
                    planning_prompt, validation.errors,
                )
                plan = None

            except (ValueError, Exception) as e:
                last_error = str(e)
                await _phase("error", f"Attempt {attempt + 1} failed: {last_error}")
                logger.warning(
                    "Planning Agent error, retrying",
                    extra={
                        "attempt": attempt + 1,
                        "error": last_error,
                        "mission_id": mission_run_id,
                    },
                )
                planning_prompt = _append_validation_feedback(
                    planning_prompt, [last_error],
                )

    # Emit planning complete event
    _sid = uuid.UUID(session_id) if session_id else uuid.uuid4()
    if plan is not None:
        await _publish(event_bus, AgentResponseCompleteEvent(
            session_id=_sid,
            source="mission_control",
            agent_id=planning_agent_id,
            full_content=f"Plan created: {len(plan.tasks)} tasks",
        ))
    else:
        await _publish(event_bus, AgentResponseCompleteEvent(
            session_id=_sid,
            source="mission_control",
            agent_id=planning_agent_id,
            full_content=last_error or "Planning failed after retries",
            metadata={"error": True},
        ))
        return ExecutionOutcome(
            mission_id=mission_run_id,
            status=ExecutionStatus.FAILED,
            planning_trace_reference=thinking_trace,
        )

    # Provision execution environment if non-local
    env_handle = None
    if execution_mode != "local":
        try:
            from modules.backend.services.execution_environment import (
                ExecutionEnvironmentService,
            )
            from modules.backend.services.container_backend import ContainerBackend
            from modules.backend.core.config import find_project_root

            env_service = ExecutionEnvironmentService(db_session=db_session)
            env_service.register_backend("container", ContainerBackend())

            repo_root = mission_repo_root or str(find_project_root())
            env_handle = await env_service.get_or_create_for_mission(
                mission_id=mission_id or mission_run_id,
                mode=execution_mode,
                config={
                    "image": "code-workspace:latest",
                    "git_aware": True,
                    "repo_root": repo_root,
                    "branch_name": f"agent/{(mission_id or mission_run_id)[:8]}/dispatch",
                },
            )
            logger.info(
                "Execution environment ready",
                extra={
                    "mode": execution_mode,
                    "environment_id": env_handle.environment_id,
                    "reused": env_handle.metadata.get("execution_count", 0) > 1,
                },
            )
        except Exception:
            logger.warning(
                "Failed to provision execution environment, falling back to local",
                extra={"mission_id": mission_id},
                exc_info=True,
            )
            env_handle = None

    # Execute dispatch loop
    outcome = await dispatch(
        plan=plan,
        roster=roster,
        execute_agent_fn=_make_agent_executor(
            event_bus,
            session_id=session_id or mission_run_id,
            mission_id=mission_id or mission_run_id,
            environment_handle=env_handle,
            current_user_id=None,  # Plan 55: resolved in Phase B
        ),
        mission_budget_usd=mission_budget_usd,
        gate=gate,
        mission_id=mission_id,
        context_curator=context_curator,
        context_assembler=context_assembler,
        event_bus=event_bus,
        session_id=session_id or mission_run_id,
        execution_mode=execution_mode,
        prior_outputs=prior_outputs,
    )

    outcome.planning_trace_reference = thinking_trace
    outcome.task_plan_reference = plan.model_dump_json()

    # Best-effort synthesis — generate human narrative summary
    from modules.backend.services.synthesis import summarize_outcome

    outcome.summary = await summarize_outcome(outcome)

    # Best-effort persistence
    if db_session is not None:
        record_id = await persist_mission_results(
            outcome,
            session_id=session_id or mission_run_id,
            roster_name=roster_name,
            task_plan_json=plan.model_dump(),
            thinking_trace=thinking_trace,
            mission_id=mission_id,
            db_session=db_session,
        )
        outcome.execution_record_id = record_id

    return outcome
