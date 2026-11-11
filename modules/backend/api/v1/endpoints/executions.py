"""
Execution Record API endpoints.

Read endpoints for querying execution history,
decisions, and cost breakdowns. Write operations happen via
the ExecutionPersistenceService called from the dispatch loop.

Runs start only through MissionRunService; this module starts no
execution. Cancel stops a record's Temporal workflow, then the record.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import (
    CurrentUser,
    DbSession,
    RequestId,
    require_mission_access,
    require_mission_operator,
)
from modules.backend.core.exceptions import AuthorizationError, NotFoundError
from modules.backend.core.logging import get_logger
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.execution_record import (
    ExecutionDecisionResponse,
    ExecutionListResponse,
    ExecutionRecordDetailResponse,
    ExecutionRecordResponse,
)
from modules.backend.services.execution_persistence import ExecutionPersistenceService

logger = get_logger(__name__)
router = APIRouter()


async def _require_execution_access(db, mission_id, user) -> None:
    """Gate an execution by its mission. Execution records inherit their
    mission's access rules; records with no mission_id are admin-only.
    """
    if mission_id:
        await require_mission_access(db, mission_id, user)
    elif not user.has_role("admin"):
        raise AuthorizationError("You don't have access to this execution")


@router.get("", response_model=ApiResponse, summary="List execution records")
async def list_executions(
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    status: str | None = None,
    roster_name: str | None = None,
    objective_category: str | None = None,
    mission_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse:
    """List execution records with optional filters.

    Reads from execution_records only — the single source of truth
    for all runs (Plan 71).
    """
    # Non-admins may only list executions within a mission they can
    # access; an unscoped listing would expose every tenant's runs.
    if not current_user.has_role("admin"):
        if not mission_id:
            raise AuthorizationError("mission_id is required to list executions")
        await require_mission_access(db, mission_id, current_user)

    service = ExecutionPersistenceService(db)
    executions, total = await service.list_executions(
        status=status,
        roster_name=roster_name,
        objective_category=objective_category,
        mission_id=mission_id,
        limit=limit,
        offset=offset,
    )

    items = [
        ExecutionRecordResponse.model_validate(e).model_copy(
            update={"task_count": len(e.task_executions or [])}
        )
        for e in executions
    ]

    return ApiResponse(
        success=True,
        data=ExecutionListResponse(
            executions=items,
            total=total,
            page_size=limit,
            offset=offset,
        ).model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}",
    response_model=ApiResponse,
    summary="Get execution record detail",
)
async def get_execution(
    execution_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get an execution record with full details.

    Reads from execution_records only (Plan 71).
    """
    service = ExecutionPersistenceService(db)
    execution = await service.get_execution(execution_id)

    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    await _require_execution_access(db, execution.mission_id, current_user)

    response = ExecutionRecordDetailResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}/decisions",
    response_model=ApiResponse,
    summary="Get execution decision audit trail",
)
async def get_execution_decisions(
    execution_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get the decision audit trail for an execution."""
    service = ExecutionPersistenceService(db)

    execution = await service.get_execution(execution_id)
    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    await _require_execution_access(db, execution.mission_id, current_user)

    decisions = await service.get_decisions(execution_id)
    items = [ExecutionDecisionResponse.model_validate(d).model_dump() for d in decisions]

    return ApiResponse(
        success=True,
        data={"decisions": items, "count": len(items)},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}/cost",
    response_model=ApiResponse,
    summary="Get execution cost breakdown",
)
async def get_execution_cost(
    execution_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get detailed cost breakdown for an execution."""
    service = ExecutionPersistenceService(db)
    execution = await service.get_execution(execution_id)
    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")
    await _require_execution_access(db, execution.mission_id, current_user)
    breakdown = await service.get_cost_breakdown(execution_id)

    return ApiResponse(
        success=True,
        data=breakdown.model_dump(),
        metadata={"request_id": request_id},
    )


# =============================================================================
# Execution control
# =============================================================================


@router.post(
    "/{execution_id}/cancel",
    response_model=ApiResponse,
    summary="Cancel an execution",
)
async def cancel_execution(
    execution_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
    reason: str = "Cancelled by user",
) -> ApiResponse:
    """Cancel a pending or running execution: Temporal first, then the record (Plan 88)."""
    from modules.backend.services.execution_cancellation import ExecutionCancellationService

    record = await ExecutionPersistenceService(db).get_execution(execution_id)
    if not record:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    if record.mission_id:
        await require_mission_operator(db, record.mission_id, current_user)
    elif not current_user.has_role("admin"):
        raise AuthorizationError("You don't have access to this execution")

    record, _changed, temporal_cancelled = await ExecutionCancellationService(db).cancel_execution(
        execution_id, user_id=str(current_user.id), reason=reason
    )
    record_id = str(record.id)
    status = record.status.value if hasattr(record.status, "value") else str(record.status)
    await db.commit()
    return ApiResponse(
        success=True,
        data={"id": record_id, "status": status, "temporal_cancelled": temporal_cancelled},
        metadata={"request_id": request_id},
    )


@router.get(
    "/{execution_id}/status",
    response_model=ApiResponse,
    summary="Get execution status",
)
async def get_execution_status(
    execution_id: str,
    db: DbSession,
    current_user: CurrentUser,
    request_id: RequestId,
) -> ApiResponse:
    """Get execution status from the database."""
    # Authorize against the execution's mission first.
    record = await ExecutionPersistenceService(db).get_execution(execution_id)
    if not record:
        raise NotFoundError(f"Execution '{execution_id}' not found")
    await _require_execution_access(db, record.mission_id, current_user)

    service = ExecutionPersistenceService(db)
    try:
        status_dict = await service.get_execution_status(execution_id)
        return ApiResponse(
            success=True,
            data={"source": "database", **status_dict},
            metadata={"request_id": request_id},
        )
    except Exception as e:
        # non-critical for mission-event visibility — re-raises
        # immediately below as a 404, which is visible to the caller
        # via the HTTP error response.
        logger.warning(
            "Execution status lookup failed",
            extra={"execution_id": execution_id, "error": str(e)},
        )
        raise NotFoundError(f"Execution '{execution_id}' not found")
