"""
Mission-scoped workflow and schedule API endpoints.

Workflow listing, import, detail, and cron schedule management.
Includes the Workflow Architect chat endpoint.
Split from missions.py for file size compliance.
"""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from modules.backend.core.dependencies import CurrentUser, DbSession, RequestId
from modules.backend.core.exceptions import AuthorizationError, NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.workflow_schedule import (
    WorkflowScheduleCreateRequest,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdateRequest,
)

router = APIRouter()


# ---- Mission-scoped workflows ----


@router.get(
    "/{mission_id}/workflows",
    response_model=ApiResponse,
    summary="List mission workflows",
)
async def list_mission_workflows(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List DB-stored workflow definitions for a mission."""
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflows = await service.list_workflows(mission_id, enabled_only=enabled_only)
    items = [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "version": w.version,
            "enabled": w.enabled,
            "trigger_type": w.trigger_type,
            "step_count": w.step_count,
            "designed_by": w.designed_by,
            "locked_at": w.locked_at,
            "edges_json": w.edges_json,
        }
        for w in workflows
    ]
    return ApiResponse(
        success=True,
        data={"workflows": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/workflow-runs",
    response_model=ApiResponse,
    summary="List workflow runs for a mission",
)
async def list_workflow_runs(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    workflow_name: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ApiResponse:
    """List past and in-flight workflow runs for a mission."""
    from modules.backend.models.execution import WorkflowRunState
    from modules.backend.repositories.workflow_run import WorkflowRunRepository

    repo = WorkflowRunRepository(db)
    status_filter = None
    if status:
        try:
            status_filter = WorkflowRunState[status.upper()]
        except KeyError:
            pass

    runs, total = await repo.list_runs(
        mission_id=mission_id,
        workflow_name=workflow_name,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    items = [
        {
            "id": r.id,
            "workflow_name": r.workflow_name,
            "workflow_version": r.workflow_version,
            "status": r.status.name if hasattr(r.status, "name") else str(r.status),
            "trigger_type": r.trigger_type,
            "triggered_by": r.triggered_by,
            "total_cost_usd": float(r.total_cost_usd or 0),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_data": r.error_data,
            "result_summary": r.result_summary,
        }
        for r in runs
    ]
    return ApiResponse(
        success=True,
        data={"runs": items, "total": total},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/workflows/import",
    response_model=ApiResponse,
    summary="Import workflow from template",
)
async def import_workflow_template(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    template_name: str = "",
    name_override: str | None = None,
) -> ApiResponse:
    """Import a YAML workflow template as a DB-stored workflow for a mission."""
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflow = await service.import_from_template(
        mission_id=mission_id,
        template_name=template_name,
        name_override=name_override,
    )
    return ApiResponse(
        success=True,
        data={
            "id": workflow.id,
            "name": workflow.name,
            "description": workflow.description,
            "mission_id": workflow.mission_id,
        },
        metadata={"request_id": request_id},
    )


@router.get(
    "/{mission_id}/workflows/{workflow_name}",
    response_model=ApiResponse,
    summary="Get mission workflow detail",
)
async def get_mission_workflow(
    mission_id: str,
    workflow_name: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get a mission workflow with full step definitions."""
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    w = await service.get_workflow(mission_id, workflow_name)
    return ApiResponse(
        success=True,
        data={
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "version": w.version,
            "enabled": w.enabled,
            "trigger_type": w.trigger_type,
            "step_count": w.step_count,
            "designed_by": w.designed_by,
            "locked_at": w.locked_at,
            "steps": w.steps,
            "edges_json": w.edges_json,
            "canvas_state": w.canvas_state,
            "objective": w.objective,
            "budget_config": w.budget_config,
            "trigger_config": w.trigger_config,
            "context": w.context,
        },
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/workflows/{workflow_name}/run",
    response_model=ApiResponse,
    summary="Run a workflow by name",
)
async def run_mission_workflow(
    mission_id: str,
    workflow_name: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Run a workflow by name against a mission.

    Resolves the workflow from mission-scoped definitions first,
    then falls back to system templates.
    """
    from modules.backend.core.config import get_redis_url
    from modules.backend.events.bus import SessionEventBus
    from modules.backend.services.workflow_run import WorkflowRunService
    from redis.asyncio import Redis as AsyncRedis

    from fastapi import HTTPException

    redis = AsyncRedis.from_url(get_redis_url())
    event_bus = SessionEventBus(redis, mission_id=mission_id)
    try:
        async with WorkflowRunService.factory(event_bus=event_bus) as svc:
            run = await svc.run_workflow(
                workflow_name=workflow_name,
                triggered_by="user:api",
                mission_id=mission_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        await redis.aclose()

    return ApiResponse(
        success=True,
        data={
            "run_id": run.id,
            "workflow_name": run.workflow_name,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "total_cost_usd": run.total_cost_usd,
        },
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/workflows/{workflow_id}",
    response_model=ApiResponse,
    summary="Delete a workflow definition",
)
async def delete_mission_workflow(
    mission_id: str,
    workflow_id: str,
    db: DbSession,
    request_id: RequestId,
    current_user: CurrentUser,
) -> ApiResponse:
    """Delete a workflow definition. Requires admin role."""
    if not current_user.has_role("admin"):
        raise AuthorizationError("Deleting workflows requires admin role")

    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    await service.delete_workflow(workflow_id)
    return ApiResponse(
        success=True,
        data={"deleted": workflow_id},
        metadata={"request_id": request_id},
    )


# ---- Workflow graph (visual editor) ----


class SaveGraphRequest(BaseModel):
    """Request body for saving workflow canvas state."""
    canvas_state: dict[str, Any] = Field(default_factory=dict)
    edges_json: list[dict[str, Any]] | None = None


@router.put(
    "/{mission_id}/workflows/{workflow_id}/graph",
    response_model=ApiResponse,
    summary="Save workflow graph canvas state",
)
async def save_workflow_graph(
    mission_id: str,
    workflow_id: str,
    data: SaveGraphRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Save canvas viewport, node positions, and optionally edges for the visual editor."""
    from modules.backend.services.workflow_definition import WorkflowDefinitionService

    service = WorkflowDefinitionService(db)
    workflow = await service.save_graph(
        workflow_id=workflow_id,
        canvas_state=data.canvas_state,
        edges_json=data.edges_json,
    )
    return ApiResponse(
        success=True,
        data={
            "id": workflow.id,
            "canvas_state": workflow.canvas_state,
            "edges_json": workflow.edges_json,
        },
        metadata={"request_id": request_id},
    )


# ---- Workflow schedules ----


@router.get(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="List mission schedules",
)
async def list_mission_schedules(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List workflow schedules for a mission."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedules = await service.list_by_mission(mission_id, enabled_only=enabled_only)
    items = [
        WorkflowScheduleResponse.model_validate(s).model_dump()
        for s in schedules
    ]
    return ApiResponse(
        success=True,
        data={"schedules": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/schedules",
    response_model=ApiResponse,
    summary="Create workflow schedule",
)
async def create_mission_schedule(
    mission_id: str,
    data: WorkflowScheduleCreateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create a cron-based schedule for a workflow."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    schedule = await service.create_schedule(
        workflow_definition_id=data.workflow_definition_id,
        mission_id=mission_id,
        cron_expression=data.cron_expression,
        timezone=data.timezone,
        description=data.description,
        budget_per_run_usd=data.budget_per_run_usd,
        max_iterations=data.max_iterations,
        cooldown_seconds=data.cooldown_seconds,
        created_by="user:api",
    )
    response = WorkflowScheduleResponse.model_validate(schedule)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.patch(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Update workflow schedule",
)
async def update_mission_schedule(
    mission_id: str,
    schedule_id: str,
    data: WorkflowScheduleUpdateRequest,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Update a workflow schedule's configuration."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    updates = data.model_dump(exclude_none=True)
    schedule = await service.update_schedule(schedule_id, **updates)
    response = WorkflowScheduleResponse.model_validate(schedule)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.delete(
    "/{mission_id}/schedules/{schedule_id}",
    response_model=ApiResponse,
    summary="Delete workflow schedule",
)
async def delete_mission_schedule(
    mission_id: str,
    schedule_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Delete a workflow schedule."""
    from modules.backend.services.workflow_schedule import WorkflowScheduleService

    service = WorkflowScheduleService(db)
    await service.delete_schedule(schedule_id)
    return ApiResponse(
        success=True,
        data={"deleted": schedule_id},
        metadata={"request_id": request_id},
    )


# ---- Workflow Architect ----


@router.post(
    "/{mission_id}/architect/chat",
    response_model=ApiResponse,
    summary="Chat with the Workflow Architect",
)
async def architect_chat(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    message: str = Query(..., min_length=1, description="Message for the Workflow Architect"),
    session_id: str | None = None,
) -> ApiResponse:
    """Send a message to the Workflow Architect for conversational design.

    The architect browses the agent catalog, proposes workflows,
    validates them, and saves confirmed designs.
    """
    from pydantic_ai.exceptions import ModelHTTPError
    from modules.backend.services.workflow_architect import WorkflowArchitectService

    service = WorkflowArchitectService(db)
    try:
        result = await service.chat(
            mission_id=mission_id,
            message=message,
            session_id=session_id,
        )
    except ModelHTTPError as e:
        body = e.body if isinstance(e.body, dict) else {}
        error_detail = body.get("error", {})
        api_message = error_detail.get("message", str(e)) if isinstance(error_detail, dict) else str(e)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=502,
            content=ApiResponse(
                success=False,
                data=None,
                error={"code": "MODEL_ERROR", "message": api_message},
                metadata={"request_id": request_id},
            ).model_dump(),
        )

    return ApiResponse(
        success=True,
        data={
            "response": result.get("response", ""),
            "usage": str(result.get("usage")) if result.get("usage") else None,
        },
        metadata={"request_id": request_id},
    )


# ---- Human Input ----


class HumanInputSubmission(BaseModel):
    """Request body for responding to a human input request."""
    response: str = Field(..., min_length=1, max_length=5000)
    responder_id: str = ""


@router.get(
    "/{mission_id}/human-input/pending",
    response_model=ApiResponse,
    summary="List pending human input requests",
)
async def list_pending_human_input(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """List pending human input requests for a mission."""
    from sqlalchemy import select

    from modules.backend.models.human_input_request import (
        HumanInputRequest,
        HumanInputRequestStatus,
    )

    result = await db.execute(
        select(HumanInputRequest)
        .where(
            HumanInputRequest.mission_id == mission_id,
            HumanInputRequest.status == HumanInputRequestStatus.PENDING,
        )
        .order_by(HumanInputRequest.created_at.desc())
    )
    requests = result.scalars().all()
    items = [
        {
            "id": r.id,
            "workflow_run_id": r.workflow_run_id,
            "step_id": r.step_id,
            "prompt_message": r.prompt_message,
            "channel": r.channel,
            "choices": r.choices_json,
            "timeout_at": r.timeout_at.isoformat() if r.timeout_at else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in requests
    ]
    return ApiResponse(
        success=True,
        data={"requests": items, "total": len(items)},
        metadata={"request_id": request_id},
    )


@router.post(
    "/{mission_id}/human-input/{input_request_id}/respond",
    response_model=ApiResponse,
    summary="Respond to a human input request",
)
async def respond_to_human_input(
    mission_id: str,
    input_request_id: str,
    data: HumanInputSubmission,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Submit a response to a pending human input request.

    Sends a Temporal Signal to the HumanInputWorkflow.
    """
    from fastapi import HTTPException
    from sqlalchemy import select

    from modules.backend.models.human_input_request import (
        HumanInputRequest,
        HumanInputRequestStatus,
    )

    result = await db.execute(
        select(HumanInputRequest).where(HumanInputRequest.id == input_request_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Human input request not found")
    if req.status != HumanInputRequestStatus.PENDING.value and req.status != HumanInputRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"Request is not pending (status: {req.status})")

    # Validate response against choices if constrained
    if req.choices_json and data.response not in req.choices_json:
        raise HTTPException(
            status_code=422,
            detail=f"Response must be one of: {', '.join(req.choices_json)}",
        )

    # Send Temporal Signal
    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.human_input_models import HumanInputResponse
    from modules.backend.temporal.human_input_workflow import HumanInputWorkflow

    client = await get_temporal_client()
    handle = client.get_workflow_handle(req.temporal_workflow_id)
    await handle.signal(
        HumanInputWorkflow.submit_human_input,
        HumanInputResponse(
            response=data.response,
            responder_id=data.responder_id,
        ),
    )

    return ApiResponse(
        success=True,
        data={"request_id": input_request_id, "status": "signal_sent"},
        metadata={"request_id": request_id},
    )
