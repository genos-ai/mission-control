"""
Mission Plan API endpoints (Plan 42).

REST surface for the long-lived mission backlog:

    GET    /missions/{id}/plan                          get plan + task states
    PATCH  /missions/{id}/plan                          update gate mode / status / budget
    POST   /missions/{id}/plan/tasks/{task_id}/approve  approve (+ transitive deps)
    POST   /missions/{id}/plan/tasks/{task_id}/reject   reject (+ transitive dependents)
    POST   /missions/{id}/plan/tasks/{task_id}/retry    failed -> approved

Phase 1.0: CRUD + state transitions only. Refinement and dispatch arrive
in Phase 1.5 and 1.6 respectively.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    get_event_bus,
)
from modules.backend.events.bus import SessionEventBus

# Plan 42 §3.5: every mutating endpoint gets an event bus so
# MissionPlanService can publish mission_plan.* events.
EventBus = Annotated[SessionEventBus, Depends(get_event_bus)]
from modules.backend.core.exceptions import AuthorizationError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission_plan import (
    AddPlanTaskRequest,
    DispatchApprovedResponse,
    MissionPlanRefineRequest,
    MissionPlanResponse,
    MissionPlanStatus,
    MissionPlanUpdate,
    PlanTaskStateResponse,
    PlanTaskStatus,
    RunObjectiveRequest,
    RunObjectiveResponse,
    TaskTransitionResponse,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.mission_plan import MissionPlanService

router = APIRouter()


# ── Access control helper ────────────────────────────────────────────────


async def _require_mission_access(
    db, mission_id: str, current_user,
) -> None:
    """Admin, mission owner, or any mission member can access the plan.

    Mirrors the access-check pattern used in missions.py. Extracted here
    because every endpoint in this file needs it.
    """
    mission_service = MissionService(db)
    mission = await mission_service.get_mission(mission_id)
    if current_user.has_role("admin"):
        return
    if mission.owner_id == current_user.id:
        return
    if await mission_service.is_member(mission_id, current_user.id):
        return
    raise AuthorizationError("You don't have access to this mission")


# ── Plan-level endpoints ─────────────────────────────────────────────────


@router.get(
    "/{mission_id}/plan",
    response_model=ApiResponse,
    summary="Get the mission plan",
)
async def get_plan(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Return the mission's plan with all task states.

    The plan is created lazily on first access — every mission has a
    plan slot even if it has never been refined.
    """
    await _require_mission_access(db, mission_id, current_user)

    # Read-only — no event bus needed
    service = MissionPlanService(db)
    plan = await service.get_or_create_plan(mission_id)

    response = MissionPlanResponse.model_validate(plan)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.patch(
    "/{mission_id}/plan",
    response_model=ApiResponse,
    summary="Update mission plan settings",
)
async def update_plan(
    mission_id: str,
    data: MissionPlanUpdate,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Update gate_mode, status, budget, veto window, or task display order.

    Only the fields present in the request body are applied — all are
    optional. Gate mode is validated against the existing gate system's
    supported values.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)

    if data.gate_mode is not None:
        plan = await service.set_gate_mode(plan.id, data.gate_mode)
    if data.status is not None:
        plan = await service.set_plan_status(
            plan.id, MissionPlanStatus(data.status),
        )
    if data.budget_usd_ceiling is not None:
        plan.budget_usd_ceiling = data.budget_usd_ceiling
        await db.flush()
    if data.veto_window_sec is not None:
        plan.veto_window_sec = data.veto_window_sec
        await db.flush()
    if data.task_order is not None and plan.task_plan_json:
        tasks: list[dict] = list(plan.task_plan_json.get("tasks", []))
        order_map = {tid: i for i, tid in enumerate(data.task_order)}
        in_order = sorted(
            [t for t in tasks if t.get("task_id") in order_map],
            key=lambda t: order_map[t.get("task_id", "")],
        )
        not_in_order = [t for t in tasks if t.get("task_id") not in order_map]
        plan.task_plan_json = {**plan.task_plan_json, "tasks": in_order + not_in_order}
        await db.flush()

    # Refetch to include updated task_states relationship
    plan = await service.get_or_create_plan(mission_id)
    response = MissionPlanResponse.model_validate(plan)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ── Refinement ───────────────────────────────────────────────────────────


@router.post(
    "/{mission_id}/plan/refine",
    response_model=ApiResponse,
    summary="Refine the mission plan via the Planning Agent",
)
async def refine_plan(
    mission_id: str,
    data: MissionPlanRefineRequest,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Refine the mission's plan using the Planning Agent.

    Delegates to MissionPlanService.refine, which invokes the Planning
    Agent in refinement mode with the current TaskPlan + the user's
    instructions. The agent returns a new TaskPlan; task states are
    reconciled in place (surviving task_ids keep their state, missing
    ones are cancelled, new ones start as proposed), and the plan's
    version counter is bumped.

    This is the single authoring entry point. The Director calls this
    via a tool when the user describes changes in chat — Plan 36
    compatibility: the Director delegates to existing code rather than
    hand-editing tasks.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    refined = await service.refine(
        plan.id,
        data.instructions,
        user_id=current_user.id,
    )

    response = MissionPlanResponse.model_validate(refined)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ── Run objective (Plan 62 — unified execution entry point) ──────────────


@router.post(
    "/{mission_id}/plan/run-objective",
    response_model=ApiResponse,
    summary="Plan, approve, and dispatch an objective in one call",
)
async def run_objective(
    mission_id: str,
    data: RunObjectiveRequest,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Unified execution entry point (Plan 62).

    Creates or refines the mission's plan from the given objective,
    auto-approves tasks (unless gate_mode is interactive), and dispatches.

    In sync mode (async_dispatch=false, default): blocks until all tasks
    complete and returns the full dispatch result. Use for CLI.

    In async mode (async_dispatch=true): approves tasks and returns
    immediately. The Temporal daemon dispatches on its next 5-second tick.
    Use for chat and frontend.

    Returns 409 Conflict if the plan has tasks currently in QUEUED or
    RUNNING state — wait for completion or cancel before starting a new run.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    result = await service.run_objective(
        mission_id=mission_id,
        objective=data.objective,
        user_id=current_user.id,
        session_id=str(request_id),
        gate_mode=data.gate_mode,
        budget_ceiling_usd=data.budget_ceiling_usd,
        async_dispatch=data.async_dispatch,
    )

    response = RunObjectiveResponse(**result)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ── Dispatch ─────────────────────────────────────────────────────────────


@router.post(
    "/{mission_id}/plan/dispatch",
    response_model=ApiResponse,
    summary="Dispatch all approved tasks as a single run",
)
async def dispatch_approved(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
    autonomous: bool = Query(
        False,
        description=(
            "If true, start a Temporal MissionRunWorkflow that loops "
            "autonomously (execute → supervisor → advance → repeat). "
            "Returns immediately with workflow_id. Falls back to inline "
            "dispatch if Temporal is not enabled."
        ),
    ),
) -> ApiResponse:
    """Start a run of every currently-approved task in the plan.

    In default mode (autonomous=false): blocks until dispatch completes
    and returns the full result with task outcomes and costs.

    In autonomous mode (autonomous=true): starts a Temporal
    MissionRunWorkflow and returns immediately. The workflow handles
    the full supervisor loop — execute, evaluate, advance/refine/
    escalate — repeating until done or a circuit breaker trips.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)

    if autonomous:
        result = await service.dispatch_autonomous(
            plan.id, session_id=str(request_id),
        )
        if result:
            response = DispatchApprovedResponse(**result)
            return ApiResponse(
                success=True,
                data=response.model_dump(),
                metadata={"request_id": request_id},
            )
        # Temporal not available — fall through to inline dispatch

    result = await service.dispatch_approved(plan.id, current_user.id)

    response = DispatchApprovedResponse(**result)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


# ── Manual task creation ─────────────────────────────────────────────────


@router.post(
    "/{mission_id}/plan/tasks",
    response_model=ApiResponse,
    summary="Add a single proposed task to the plan",
)
async def add_plan_task(
    mission_id: str,
    data: AddPlanTaskRequest,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Append a manually-created proposed task to the plan's task_plan_json.

    Initialises task_plan_json if the plan has none yet. The task starts
    in proposed state and follows the same approve → dispatch flow as
    Planning-Agent-generated tasks.
    """
    await _require_mission_access(db, mission_id, current_user)
    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    updated = await service.add_task(
        plan.id,
        description=data.description,
        agent=data.agent,
        instructions=data.instructions,
        dependencies=data.dependencies,
    )
    return ApiResponse(
        success=True,
        data=MissionPlanResponse.model_validate(updated).model_dump(),
        metadata={"request_id": request_id},
    )


# ── Task-level state transitions ─────────────────────────────────────────


@router.post(
    "/{mission_id}/plan/tasks/{task_id}/approve",
    response_model=ApiResponse,
    summary="Approve a plan task (with transitive dependencies)",
)
async def approve_task(
    mission_id: str,
    task_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Approve a task and all of its transitive dependencies.

    Only proposed tasks are transitioned — already-approved / running /
    completed dependencies are left as-is. The response lists every
    task_id that actually changed so the UI can visually highlight the
    closure (e.g. "approving this task also approved 2 dependencies").
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    transitioned = await service.approve_task(plan.id, task_id, current_user.id)

    response = TaskTransitionResponse(
        target_task_id=task_id,
        transitioned_task_ids=[s.task_id for s in transitioned],
        new_status=PlanTaskStatus.APPROVED.value,
    )
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/plan/tasks/{task_id}/reject",
    response_model=ApiResponse,
    summary="Reject a plan task (with transitive dependents)",
)
async def reject_task(
    mission_id: str,
    task_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Reject a task and cancel all transitive dependents.

    Running tasks are not affected by rejection — cancel an in-flight
    run through the execution endpoints instead.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    transitioned = await service.reject_task(plan.id, task_id, current_user.id)

    response = TaskTransitionResponse(
        target_task_id=task_id,
        transitioned_task_ids=[s.task_id for s in transitioned],
        new_status=PlanTaskStatus.CANCELLED.value,
    )
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/plan/tasks/{task_id}/retry",
    response_model=ApiResponse,
    summary="Retry a failed plan task",
)
async def retry_task(
    mission_id: str,
    task_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Move a failed task back into `approved` so it can be re-dispatched.

    Dependencies are NOT re-walked — they already completed successfully
    last run. If the failure was caused by a dep, reject the dep first
    and the cascade will cancel this task too.
    """
    await _require_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    state = await service.retry_task(plan.id, task_id, current_user.id)

    response = PlanTaskStateResponse.model_validate(state)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )
