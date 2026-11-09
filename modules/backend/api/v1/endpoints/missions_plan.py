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

from fastapi import APIRouter, Depends

from modules.backend.core.config import get_app_config
from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    get_event_bus,
    require_existing_mission_access,
    require_mission_operator,
)
from modules.backend.core.logging import get_logger
from modules.backend.events.bus import SessionEventBus
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission_plan import (
    AddPlanTaskRequest,
    MissionPlanRefineRequest,
    MissionPlanResponse,
    MissionPlanStatus,
    MissionPlanUpdate,
    RunObjectiveRequest,
    TaskStatus,
    TaskTransitionResponse,
)
from modules.backend.schemas.mission_run import MissionRunResponse, MissionRunTrigger
from modules.backend.services.mission_plan import MissionPlanService, remaining_plan_budget_usd
from modules.backend.services.mission_run import MissionRunService

# Plan 42 §3.5: every mutating endpoint gets an event bus so
# MissionPlanService can publish mission_plan.* events.
EventBus = Annotated[SessionEventBus, Depends(get_event_bus)]

logger = get_logger(__name__)

router = APIRouter()


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
    await require_existing_mission_access(db, mission_id, current_user)

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
    """Update gate_mode, status, budget, or task display order.

    Only the fields present in the request body are applied — all are
    optional. Gate mode is validated against the existing gate system's
    supported values.
    """
    await require_mission_operator(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)

    if data.gate_mode is not None:
        plan = await service.set_gate_mode(plan.id, data.gate_mode)
    if data.status is not None:
        plan = await service.set_plan_status(
            plan.id,
            MissionPlanStatus(data.status),
        )
    if data.budget_usd_ceiling is not None:
        plan.budget_usd_ceiling = data.budget_usd_ceiling
        await db.flush()
    # Plan 72: task ordering is by created_at — no manual reorder needed.

    # Refetch to include updated tasks relationship
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

    Starts a PlanRefineWorkflow via Temporal and returns immediately.
    The workflow emits mission_plan.refined via SSE on completion,
    or a system.info error event on failure.

    This is the single authoring entry point. The Director calls this
    via a tool when the user describes changes in chat — Plan 36
    compatibility: the Director delegates to existing code rather than
    hand-editing tasks.
    """
    import uuid as _uuid

    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.plan_refine_models import PlanRefineInput
    from modules.backend.temporal.plan_refine_workflow import PlanRefineWorkflow

    await require_existing_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)

    client = await get_temporal_client()
    config = get_app_config().temporal

    workflow_id = f"plan-refine-{plan.id[:12]}-{_uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        PlanRefineWorkflow.run,
        PlanRefineInput(
            mission_id=mission_id,
            plan_id=plan.id,
            instructions=data.instructions,
            user_id=current_user.id,
            mission_budget_usd=remaining_plan_budget_usd(plan),
        ),
        id=workflow_id,
        task_queue=config.task_queue,
    )

    return ApiResponse(
        success=True,
        data={
            "status": "refining",
            "plan_id": plan.id,
            "workflow_id": workflow_id,
        },
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

    Starts a RunObjectiveWorkflow via Temporal and returns immediately.
    The workflow runs: refine (Planning Agent) → approve → dispatch
    (MissionRunWorkflow). Progress is streamed via SSE.

    Returns 409 Conflict if the plan has tasks currently in QUEUED or
    RUNNING state — wait for completion or cancel before starting a new run.
    """
    import uuid as _uuid

    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.run_objective_models import RunObjectiveInput
    from modules.backend.temporal.run_objective_workflow import RunObjectiveWorkflow

    await require_existing_mission_access(db, mission_id, current_user)

    # Validate plan exists and check for in-flight tasks before
    # starting the workflow (fast DB check — fails early on 409).
    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    await service.check_no_active_tasks(plan.id)

    client = await get_temporal_client()
    config = get_app_config().temporal

    workflow_id = f"run-objective-{mission_id[:12]}-{_uuid.uuid4().hex[:8]}"
    await client.start_workflow(
        RunObjectiveWorkflow.run,
        RunObjectiveInput(
            mission_id=mission_id,
            objective=data.objective,
            user_id=current_user.id,
            session_id=str(request_id),
            gate_mode=data.gate_mode,
            budget_ceiling_usd=data.budget_ceiling_usd,
        ),
        id=workflow_id,
        task_queue=config.task_queue,
    )

    return ApiResponse(
        success=True,
        data={
            "plan_id": plan.id,
            "outcome_status": "dispatching",
            "workflow_id": workflow_id,
        },
        metadata={"request_id": request_id},
    )


# ── Dispatch ─────────────────────────────────────────────────────────────


@router.post(
    "/{mission_id}/plan/dispatch",
    response_model=ApiResponse,
    summary="Start a mission run for the approved backlog",
)
async def dispatch_approved(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
    event_bus: EventBus,
) -> ApiResponse:
    """Start a mission run that dispatches the approved backlog.

    Returns the PENDING run; its MissionRunWorkflow adopts the approved
    tasks when it begins. 409 when another run of the mission is active.
    """
    await require_mission_operator(db, mission_id, current_user)

    run = await MissionRunService(db, event_bus).start_run(
        mission_id,
        trigger=MissionRunTrigger.MANUAL,
        objective=None,
        user_id=current_user.id,
        session_id=None,
    )
    return ApiResponse(
        success=True,
        data=MissionRunResponse.model_validate(run).model_dump(mode="json"),
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
    """Add a manually-created proposed task to the plan.

    Creates a Task row directly (Plan 72). The task starts
    in proposed state and follows the same approve → dispatch flow as
    Planning-Agent-generated tasks.
    """
    await require_existing_mission_access(db, mission_id, current_user)
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
    await require_existing_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    transitioned = await service.approve_task(plan.id, task_id, current_user.id)
    # A dispatcher blocked on these tasks polls the task rows (Plan 88.0.13a).

    response = TaskTransitionResponse(
        target_task_id=task_id,
        transitioned_task_ids=[t.id for t in transitioned],
        new_status=TaskStatus.APPROVED,
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
    await require_existing_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    transitioned = await service.reject_task(plan.id, task_id, current_user.id)

    response = TaskTransitionResponse(
        target_task_id=task_id,
        transitioned_task_ids=[t.id for t in transitioned],
        new_status=TaskStatus.CANCELLED,
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
    await require_existing_mission_access(db, mission_id, current_user)

    service = MissionPlanService(db, event_bus=event_bus)
    plan = await service.get_or_create_plan(mission_id)
    task = await service.retry_task(plan.id, task_id, current_user.id)

    response = TaskTransitionResponse(
        target_task_id=task_id,
        transitioned_task_ids=[task.id],
        new_status=TaskStatus.APPROVED,
    )
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )
