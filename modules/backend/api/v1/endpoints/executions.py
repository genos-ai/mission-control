"""
Execution Record API endpoints.

Read endpoints for querying execution history,
decisions, and cost breakdowns. Write operations happen via
the ExecutionPersistenceService called from the dispatch loop.

Temporal endpoints (execute, approve, status) are gated by
the temporal.enabled feature flag.
"""

from fastapi import APIRouter

from modules.backend.core.dependencies import DbSession, RequestId
from modules.backend.core.exceptions import NotFoundError
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)
from modules.backend.schemas.base import ApiResponse
from modules.backend.schemas.execution_record import (
    ExecutionCostBreakdown,
    ExecutionDecisionResponse,
    ExecutionListResponse,
    ExecutionRecordDetailResponse,
    ExecutionRecordResponse,
)
from modules.backend.services.execution_persistence import ExecutionPersistenceService

router = APIRouter()


@router.get("", response_model=ApiResponse, summary="List execution records")
async def list_executions(
    db: DbSession,
    request_id: RequestId,
    status: str | None = None,
    roster_name: str | None = None,
    objective_category: str | None = None,
    mission_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ApiResponse:
    """List execution records with optional filters."""
    service = ExecutionPersistenceService(db)
    executions, total = await service.list_executions(
        status=status,
        roster_name=roster_name,
        objective_category=objective_category,
        mission_id=mission_id,
        limit=limit,
        offset=offset,
    )

    return ApiResponse(
        success=True,
        data=ExecutionListResponse(
            executions=[ExecutionRecordResponse.model_validate(e) for e in executions],
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
    request_id: RequestId,
) -> ApiResponse:
    """Get an execution record with full details."""
    service = ExecutionPersistenceService(db)
    execution = await service.get_execution(execution_id)

    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

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
    request_id: RequestId,
) -> ApiResponse:
    """Get the decision audit trail for an execution."""
    service = ExecutionPersistenceService(db)

    execution = await service.get_execution(execution_id)
    if not execution:
        raise NotFoundError(f"Execution '{execution_id}' not found")

    decisions = await service.get_decisions(execution_id)
    items = [
        ExecutionDecisionResponse.model_validate(d).model_dump()
        for d in decisions
    ]

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
    request_id: RequestId,
) -> ApiResponse:
    """Get detailed cost breakdown for an execution."""
    service = ExecutionPersistenceService(db)
    breakdown = await service.get_cost_breakdown(execution_id)

    return ApiResponse(
        success=True,
        data=breakdown.model_dump(),
        metadata={"request_id": request_id},
    )


# =============================================================================
# Execution dispatch
# =============================================================================


@router.post(
    "/{execution_id}/execute",
    response_model=ApiResponse,
    summary="Execute an execution",
)
async def execute_execution(
    execution_id: str,
    db: DbSession,
    request_id: RequestId,
) -> ApiResponse:
    """Execute a dispatch. Uses Temporal when enabled, direct dispatch otherwise."""
    from modules.backend.core.config import get_app_config
    from modules.backend.services.execution import ExecutionService
    from modules.backend.agents.mission_control.dispatch_adapter import (
        MissionControlDispatchAdapter,
    )
    from modules.backend.services.session import SessionService

    config = get_app_config()

    if config.temporal.enabled:
        service = ExecutionService(session=db)
        result = await service.start_temporal_execution(execution_id)
        return ApiResponse(
            success=True,
            data=result,
            metadata={"request_id": request_id},
        )

    session_service = SessionService(db)
    adapter = MissionControlDispatchAdapter(
        session_service=session_service,
        db_session=db,
    )
    service = ExecutionService(
        session=db,
        mission_control_dispatch=adapter,
        session_service=session_service,
    )
    execution = await service.run_execution(execution_id)

    from modules.backend.schemas.execution import ExecutionResponse
    response = ExecutionResponse.model_validate(execution)
    return ApiResponse(
        success=True,
        data=response.model_dump(),
        metadata={"request_id": request_id},
    )


@router.post(
    "/{execution_id}/approve",
    response_model=ApiResponse,
    summary="Submit approval for an execution",
)
async def submit_approval(
    execution_id: str,
    decision: str,
    responder_id: str,
    request_id: RequestId,
    reason: str | None = None,
) -> ApiResponse:
    """Send an approval decision to a waiting Temporal workflow."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()
    if not config.temporal.enabled:
        return ApiResponse(
            success=False,
            data={
                "error": "temporal_not_enabled",
                "message": "Approval signals require Temporal.",
            },
            metadata={"request_id": request_id},
        )

    from modules.backend.temporal.client import get_temporal_client
    from modules.backend.temporal.models import ApprovalDecision
    from modules.backend.temporal.workflow import AgentMissionWorkflow

    client = await get_temporal_client()
    handle = client.get_workflow_handle(f"execution-{execution_id}")

    await handle.signal(
        AgentMissionWorkflow.submit_approval,
        ApprovalDecision(
            decision=decision,
            responder_type="human",
            responder_id=responder_id,
            reason=reason,
        ),
    )

    return ApiResponse(
        success=True,
        data={
            "execution_id": execution_id,
            "decision": decision,
            "status": "signal_sent",
        },
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
    request_id: RequestId,
) -> ApiResponse:
    """Get execution status — Temporal Query or DB fallback."""
    from modules.backend.core.config import get_app_config

    config = get_app_config()

    if config.temporal.enabled:
        try:
            from modules.backend.temporal.client import get_temporal_client
            from modules.backend.temporal.workflow import AgentMissionWorkflow

            client = await get_temporal_client()
            handle = client.get_workflow_handle(f"execution-{execution_id}")
            status = await handle.query(AgentMissionWorkflow.get_status)
            return ApiResponse(
                success=True,
                data={
                    "source": "temporal",
                    "execution_id": status.mission_id,
                    "workflow_status": status.workflow_status,
                    "execution_status": status.mission_status,
                    "total_cost_usd": status.total_cost_usd,
                    "waiting_for_approval": status.waiting_for_approval,
                    "error": status.error,
                },
                metadata={"request_id": request_id},
            )
        except Exception as e:
            logger.debug(
                "Temporal status query failed, falling back to DB",
                extra={"execution_id": execution_id, "error": str(e)},
            )

    service = ExecutionPersistenceService(db)
    try:
        status_dict = await service.get_execution_status(execution_id)
        return ApiResponse(
            success=True,
            data={"source": "database", **status_dict},
            metadata={"request_id": request_id},
        )
    except Exception as e:
        logger.warning(
            "Execution status lookup failed",
            extra={"execution_id": execution_id, "error": str(e)},
        )
        raise NotFoundError(f"Execution '{execution_id}' not found")
