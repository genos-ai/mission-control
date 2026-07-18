"""
Workflow and Mission API endpoints.

Provides endpoints for listing workflows, creating missions,
and monitoring mission status.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.schemas.base import ApiResponse
from modules.backend.services.workflow import WorkflowService

router = APIRouter()


def _get_workflow_service() -> WorkflowService:
    return WorkflowService()


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


# ---- Mission endpoints (reads from execution_records — Plan 71) ----


@router.post(
    "/missions",
    response_model=ApiResponse,
    summary="Create ad-hoc mission (DEPRECATED)",
)
async def create_execution(
    request_id: RequestId,
) -> ApiResponse:
    """DEPRECATED (Plan 62): Use MissionPlanService.run_objective() instead."""
    return ApiResponse(
        success=False,
        data={
            "error": "deprecated",
            "message": (
                "Ad-hoc execution creation is deprecated (Plan 62). "
                "Use the plan dispatch path instead."
            ),
        },
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
    mission_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse:
    """List missions from execution_records."""
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    service = ExecutionPersistenceService(db)
    runs, total = await service.list_all_runs(
        mission_id=mission_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return ApiResponse(
        success=True,
        data={"executions": runs, "total": total},
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
    """Get detailed mission info from execution_records."""
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    service = ExecutionPersistenceService(db)
    record = await service.get_execution(mission_id)

    if not record:
        raise NotFoundError(
            message=f"Execution '{mission_id}' not found",
        )

    status = record.status.value if hasattr(record.status, "value") else str(record.status)
    return ApiResponse(
        success=True,
        data={
            "id": str(record.id),
            "session_id": str(record.session_id) if record.session_id else None,
            "roster_name": record.roster_name,
            "status": status,
            "total_cost_usd": float(record.total_cost_usd or 0),
            "objective_statement": record.objective_statement,
            "execution_outcome_json": record.execution_outcome_json,
            "started_at": str(record.started_at) if record.started_at else None,
            "completed_at": str(record.completed_at) if record.completed_at else None,
        },
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
    """Cancel a running or pending mission via execution_records."""
    from modules.backend.services.execution_persistence import ExecutionPersistenceService

    service = ExecutionPersistenceService(db)
    record = await service.get_execution(mission_id)

    if not record:
        raise NotFoundError(
            message=f"Execution '{mission_id}' not found",
        )

    status = record.status.value if hasattr(record.status, "value") else str(record.status)
    if status.lower() in ("completed", "failed", "cancelled", "timed_out"):
        return ApiResponse(
            success=True,
            data={"id": str(record.id), "status": status, "message": "Already terminal"},
            metadata={"request_id": request_id},
        )

    await service.complete_execution(
        execution_record_id=str(record.id),
        status="cancelled",
    )
    await db.commit()

    return ApiResponse(
        success=True,
        data={"id": str(record.id), "status": "cancelled"},
        metadata={"request_id": request_id},
    )
