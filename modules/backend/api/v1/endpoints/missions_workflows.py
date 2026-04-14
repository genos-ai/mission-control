"""
Mission-scoped workflow and schedule API endpoints.

Workflow listing, import, detail, and cron schedule management.
Includes the Workflow Architect chat endpoint.
Split from missions.py for file size compliance.
"""

from fastapi import APIRouter, Query

from modules.backend.core.dependencies import DbSession, RequestId
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
        }
        for w in workflows
    ]
    return ApiResponse(
        success=True,
        data={"workflows": items, "total": len(items)},
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
    from modules.backend.services.workflow_run import WorkflowRunService

    from fastapi import HTTPException

    try:
        async with WorkflowRunService.factory() as svc:
            run = await svc.run_workflow(
                workflow_name=workflow_name,
                triggered_by="user:api",
                mission_id=mission_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

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
