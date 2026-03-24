"""
Workflow and Mission API endpoints.

Provides endpoints for listing workflows, creating missions,
and monitoring mission status.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.execution import (
    ExecutionCreate,
    ExecutionDetailResponse,
    ExecutionResponse,
)

from modules.backend.services.execution import ExecutionService
from modules.backend.services.workflow import WorkflowService

router = APIRouter()


def _get_workflow_service() -> WorkflowService:
    return WorkflowService()


def _get_execution_service(db: DbSession) -> ExecutionService:
    return ExecutionService(session=db)


# ---- Workflow endpoints ----


@router.get("", response_model=ApiResponse, summary="List workflows")
async def list_workflows(
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List available workflows."""
    service = _get_workflow_service()
    workflows = service.list_workflows(enabled_only=enabled_only)

    items = [service.to_list_item(w) for w in workflows]

    return ApiResponse(
        success=True,
        data={"workflows": items},
        metadata={"request_id": request_id, "count": len(items)},
    )


@router.get(
    "/{workflow_name}",
    response_model=ApiResponse,
    summary="Get workflow detail",
)
async def get_workflow(
    workflow_name: str,
    request_id: RequestId,
) -> ApiResponse:
    """Get a specific workflow with full details."""
    service = _get_workflow_service()
    workflow = service.get_workflow(workflow_name)

    if not workflow:
        raise NotFoundError(
            message=f"Workflow '{workflow_name}' not found",
        )

    return ApiResponse(
        success=True,
        data=service.to_detail(workflow),
        metadata={"request_id": request_id},
    )


# ---- Mission endpoints ----


@router.post(
    "/missions",
    response_model=ApiResponse,
    summary="Create ad-hoc mission",
)
async def create_execution(
    data: ExecutionCreate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create and start an ad-hoc execution."""
    service = _get_execution_service(db)

    execution = await service.create_adhoc_execution(
        objective=data.objective,
        triggered_by=data.triggered_by,
        roster_ref=data.roster_ref,
        complexity_tier=data.complexity_tier,
        cost_ceiling_usd=data.cost_ceiling_usd,
        upstream_context=data.upstream_context,
    )

    response = ExecutionResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/missions",
    response_model=ApiResponse,
    summary="List missions",
)
async def list_missions(
    db: DbSession,
    request_id: RequestId,
    status: str | None = None,
    workflow_run_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse:
    """List missions with optional filters."""
    service = _get_execution_service(db)
    executions, total = await service.list_executions(
        status=status,
        workflow_run_id=workflow_run_id,
        limit=limit,
        offset=offset,
    )

    items = [ExecutionResponse.model_validate(m).model_dump() for m in executions]
    return ApiResponse(
        success=True,
        data={"executions": items, "total": total},
        metadata={"request_id": request_id},
    )


@router.get(
    "/missions/{mission_id}",
    response_model=ApiResponse,
    summary="Get mission detail",
)
async def get_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Get detailed mission info including context and results."""
    service = _get_execution_service(db)
    execution = await service.get_execution(mission_id)

    response = ExecutionDetailResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/missions/{mission_id}/cancel",
    response_model=ApiResponse,
    summary="Cancel mission",
)
async def cancel_mission(
    mission_id: str,
    db: DbSession,
    request_id: RequestId,
    reason: str = "User cancelled",
) -> ApiResponse:
    """Cancel a running or pending mission."""
    service = _get_execution_service(db)
    execution = await service.cancel_execution(mission_id, reason=reason)

    response = ExecutionResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )
