"""
Workflow and Mission API endpoints.

Provides endpoints for listing workflows, creating missions,
and monitoring mission status.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.mission import (
    MissionCreate,
    MissionDetailResponse,
    MissionResponse,
)
from modules.backend.schemas.workflow import (
    WorkflowDetailResponse,
    WorkflowListResponse,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.workflow import WorkflowService

router = APIRouter()


def _get_workflow_service() -> WorkflowService:
    return WorkflowService()


def _get_mission_service(db: DbSession) -> MissionService:
    return MissionService(session=db)


# ---- Workflow endpoints ----


@router.get("", response_model=ApiResponse, summary="List workflows")
async def list_workflows(
    request_id: RequestId,
    enabled_only: bool = True,
) -> ApiResponse:
    """List available workflows."""
    service = _get_workflow_service()
    workflows = service.list_workflows(enabled_only=enabled_only)

    items = [
        WorkflowListResponse(
            workflow_name=w.workflow_name,
            description=w.description,
            version=w.version,
            enabled=w.enabled,
            trigger_type=w.trigger.type,
            step_count=len(w.steps),
            budget_usd=w.budget.max_cost_usd,
            objective_category=w.objective.category,
            objective_priority=w.objective.priority,
            objective_owner=w.objective.owner,
        )
        for w in workflows
    ]

    return ApiResponse(
        success=True,
        data={"workflows": [item.model_dump() for item in items]},
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

    detail = WorkflowDetailResponse(
        workflow_name=workflow.workflow_name,
        description=workflow.description,
        objective=workflow.objective,
        version=workflow.version,
        enabled=workflow.enabled,
        trigger=workflow.trigger,
        budget=workflow.budget,
        context_keys=list(workflow.context.keys()),
        steps=workflow.steps,
    )

    return ApiResponse(
        success=True,
        data=detail.model_dump(),
        metadata={"request_id": request_id},
    )


# ---- Mission endpoints ----


@router.post(
    "/missions",
    response_model=ApiResponse,
    summary="Create ad-hoc mission",
)
async def create_mission(
    data: MissionCreate,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Create and start an ad-hoc mission."""
    from uuid import uuid4

    service = _get_mission_service(db)
    session_id = str(uuid4())

    mission = await service.create_adhoc_mission(
        objective=data.objective,
        triggered_by=data.triggered_by,
        session_id=session_id,
        roster_ref=data.roster_ref,
        complexity_tier=data.complexity_tier,
        cost_ceiling_usd=data.cost_ceiling_usd,
        upstream_context=data.upstream_context,
    )

    response = MissionResponse.model_validate(mission)
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
    service = _get_mission_service(db)
    missions, total = await service.list_missions(
        status=status,
        playbook_run_id=workflow_run_id,
        limit=limit,
        offset=offset,
    )

    items = [MissionResponse.model_validate(m).model_dump() for m in missions]
    return ApiResponse(
        success=True,
        data={"missions": items, "total": total},
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
    service = _get_mission_service(db)
    mission = await service.get_mission(mission_id)

    response = MissionDetailResponse.model_validate(mission)
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
    service = _get_mission_service(db)
    mission = await service.cancel_mission(mission_id, reason=reason)

    response = MissionResponse.model_validate(mission)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )
